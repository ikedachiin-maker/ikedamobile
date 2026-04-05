"""
reassign.py — SIMカード再割り当てスクリプト

問題のあるSIMカード（他人名義でMNP予約番号が発行済み等）を
新しいSIMカードに差し替え、顧客情報を再入力して予約番号を取得する。

タスク定義: reassign_config.json

■ 処理フロー:
  1. reassign_config.json から pending タスクを読み込み
  2. 割り当てシートから対象行の情報を取得
  3. 申し込み管理シートから顧客情報（フリガナ、生年月日、性別等）を取得
  4. jpmob にログインし、利用可能なSIMカードを検索
     → 不足の場合は pending のまま終了（watcher が次回再試行）
  5. 新しいSIMカードに顧客情報を入力（1枚ずつシートも即更新）
  6. 60分待機（SEND_DELAY_SECONDS）
  7. 予約番号取得（最大6回リトライ）
  8. 割り当てシートに予約番号・有効期限を更新
  9. メール送信
  10. config の status を completed に更新
"""

import os
import json
import time
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from jpmob_automator import (
    create_driver,
    login,
    get_open_cards,
    enter_user_info,
    fetch_reservations,
    _load_skip_cache,
    _load_entered_cards,
)
from assignment_sheet import (
    get_processed_card_ids,
    get_assignments_by_phones,
    update_sim_assignment,
    update_reservation_info,
)
from application_sheet import get_or_create_application_sheet
from gmail_sender import send_gmail

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "reassign_config.json")


# ─── Config ファイル操作 ──────────────────────────────────

def load_config() -> dict:
    """reassign_config.json を読み込む"""
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"tasks": []}


def save_config(config: dict) -> None:
    """reassign_config.json を保存する（atomic write）"""
    tmp_path = CONFIG_FILE + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, CONFIG_FILE)


# ─── 顧客情報の取得 ──────────────────────────────────────

def get_customer_record(email: str) -> dict | None:
    """
    申し込み管理シートからメールアドレスで顧客情報を検索する。
    enter_user_info() が必要とする6項目（フリガナ、漢字、生年月日、性別）を返す。
    """
    ws = get_or_create_application_sheet()
    all_records = ws.get_all_records()

    for rec in all_records:
        if (rec.get("メールアドレス") or "").strip().lower() == email.lower():
            return {
                "姓（漢字）":     rec.get("姓（漢字）", ""),
                "名（漢字）":     rec.get("名（漢字）", ""),
                "姓（フリガナ）": rec.get("姓（フリガナ）", ""),
                "名（フリガナ）": rec.get("名（フリガナ）", ""),
                "生年月日":       rec.get("生年月日", ""),
                "性別":           rec.get("性別", ""),
                "メールアドレス": rec.get("メールアドレス", ""),
            }

    return None


# ─── 利用可能なSIMカードの検索 ────────────────────────────

def find_available_sims(driver, wait, count: int, extra_exclude_ids: set[str]) -> list[dict]:
    """
    jpmob から利用可能なSIMカードを count 枚探す。
    extra_exclude_ids: 追加で除外するカードID（古いSIMカード等）

    Returns:
        count 枚以上見つかれば先頭 count 枚のリスト
        不足なら空リスト
    """
    all_open_cards = get_open_cards(driver, wait)
    if not all_open_cards:
        print("[reassign] 開通済みカードが見つかりません")
        return []

    processed_ids = get_processed_card_ids()
    skip_cache = _load_skip_cache()
    entered_cards = _load_entered_cards()

    exclude_ids = processed_ids | skip_cache | entered_cards | extra_exclude_ids
    available = [c for c in all_open_cards if c["card_id"] not in exclude_ids]

    print(
        f"[reassign] 開通済み {len(all_open_cards)} 件 → "
        f"除外 {len(all_open_cards) - len(available)} 件 → "
        f"利用可能 {len(available)} 件（必要 {count} 件）"
    )

    if len(available) < count:
        return []

    return available[:count]


# ─── メイン処理 ──────────────────────────────────────────

def main():
    print("=" * 55)
    print("  SIMカード 再割り当てスクリプト")
    print(f"  実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    # ── Step 1: pending タスクを読み込み ─────────────────
    config = load_config()
    pending_tasks = [t for t in config["tasks"] if t.get("status") == "pending"]

    if not pending_tasks:
        print("\n[Step 1] pending のタスクはありません。処理を終了します。")
        return

    task = pending_tasks[0]
    old_phones = task["old_sim_phones"]
    print(f"\n[Step 1] タスク '{task['id']}' を処理します（{len(old_phones)} 回線）")
    for p in old_phones:
        print(f"  差し替え対象: {p}")

    # status を in_progress に更新
    task["status"] = "in_progress"
    task["started_at"] = datetime.now().isoformat()
    save_config(config)

    # ── Step 2: 割り当てシートから対象行の情報を取得 ─────
    print("\n[Step 2] 割り当てシートから対象行を取得中...")
    existing = get_assignments_by_phones(old_phones)

    if not existing:
        print("[reassign] 割り当てシートに対象レコードが見つかりません。処理を中止します。")
        task["status"] = "pending"
        save_config(config)
        return

    # 既に差し替え済みの電話番号をスキップ（部分再実行時）
    found_phones = {r["SIM電話番号"].strip() for r in existing}
    phones_to_replace = [p for p in old_phones if p in found_phones]

    if not phones_to_replace:
        print("[reassign] 差し替え対象の電話番号がすべて既に更新済みです。完了とみなします。")
        task["status"] = "completed"
        task["completed_at"] = datetime.now().isoformat()
        save_config(config)
        return

    print(f"  差し替え対象: {len(phones_to_replace)} 件")

    # メールアドレスを取得（全行同一顧客のはず）
    email = existing[0].get("メールアドレス", "").strip()
    if not email:
        print("[reassign] メールアドレスが取得できません。処理を中止します。")
        task["status"] = "pending"
        save_config(config)
        return
    print(f"  顧客メール: {email}")

    # 古いカードIDを取得（除外用）
    old_card_ids = {r["カードID"].strip() for r in existing if r["カードID"].strip()}

    # ── Step 3: 申し込み管理シートから顧客情報を取得 ─────
    print("\n[Step 3] 申し込み管理シートから顧客情報を取得中...")
    record = get_customer_record(email)

    if not record:
        print(f"[reassign] メールアドレス '{email}' の顧客情報が見つかりません。処理を中止します。")
        task["status"] = "pending"
        save_config(config)
        return

    # 必須項目の確認
    required = ["姓（フリガナ）", "名（フリガナ）", "姓（漢字）", "名（漢字）", "生年月日", "性別"]
    missing = [f for f in required if not str(record.get(f, "")).strip()]
    if missing:
        print(f"[reassign] 顧客情報に不足があります: {', '.join(missing)}")
        task["status"] = "pending"
        save_config(config)
        return

    customer_name = f"{record['姓（漢字）']} {record['名（漢字）']}".strip()
    print(f"  顧客名: {customer_name}")
    print(f"  フリガナ: {record['姓（フリガナ）']} {record['名（フリガナ）']}")

    # ── Step 4: jpmob にログインし、利用可能なSIMカードを検索 ──
    print(f"\n[Step 4] jpmob にログインし、利用可能なSIMカードを検索中...")

    username = os.getenv("JPMOB_USERNAME")
    password = os.getenv("JPMOB_PASSWORD")
    if not all([username, password]):
        raise ValueError("[reassign] .env の JPMOB_USERNAME / JPMOB_PASSWORD が未設定です")

    driver = create_driver(headless=True)
    from selenium.webdriver.support.ui import WebDriverWait
    wait = WebDriverWait(driver, 15)

    try:
        login(driver, wait, username, password)

        new_sims = find_available_sims(driver, wait, len(phones_to_replace), old_card_ids)

        if not new_sims:
            print(
                f"[reassign] 利用可能なSIMカードが不足しています。"
                f"次回の watcher チェックで再試行します。"
            )
            task["status"] = "pending"
            save_config(config)
            return

        for sim in new_sims:
            print(f"  割り当て予定: {sim['phone']} (card_id={sim['card_id']})")

        # ── Step 5: 新しいSIMカードに顧客情報を入力 ────
        print(f"\n[Step 5] 新しいSIMカードに顧客情報を入力中...")

        assignments = []
        sim_index = 0

        for old_phone in phones_to_replace:
            success = False
            while sim_index < len(new_sims):
                new_sim = new_sims[sim_index]
                sim_index += 1

                print(f"  入力中: {customer_name} → SIM {new_sim['phone']} (card_id={new_sim['card_id']})")
                entered = enter_user_info(driver, wait, new_sim["card_id"], record)

                if entered:
                    entered_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    # 割り当てシートを即座に更新（部分失敗に対応）
                    update_sim_assignment(old_phone, new_sim["phone"], new_sim["card_id"], entered_at)

                    assignments.append({
                        "record":        record,
                        "sim_phone":     new_sim["phone"],
                        "card_id":       new_sim["card_id"],
                        "entered_at":    entered_at,
                        "yoyaku_number": "",
                        "expiry_date":   "",
                    })
                    success = True
                    break
                else:
                    print(f"  スキップ: card_id={new_sim['card_id']} — 次のSIMカードを試行")

            if not success:
                print(f"  ⚠️ {old_phone} の差し替え先が見つかりませんでした")

        print(f"\n  入力完了: {len(assignments)} / {len(phones_to_replace)} 件")

        if not assignments:
            print("[reassign] 1件も入力できませんでした。次回再試行します。")
            task["status"] = "pending"
            save_config(config)
            return

    finally:
        driver.quit()

    # ── Step 6: 予約番号発行まで待機 ─────────────────
    delay_seconds = int(os.getenv("SEND_DELAY_SECONDS", "3600"))
    delay_min = delay_seconds // 60
    print(f"\n[Step 6] {delay_min} 分後に予約番号を取得します...")
    time.sleep(delay_seconds)

    # ── Step 7: 予約番号取得（リトライあり）──────────
    retry_interval = int(os.getenv("RETRY_INTERVAL_SECONDS", "1800"))
    max_retries = int(os.getenv("MAX_RETRIES", "6"))

    for attempt in range(1, max_retries + 1):
        print(f"\n[Step 7] 予約番号を取得中... (試行 {attempt}/{max_retries})")
        assignments = fetch_reservations(assignments)

        issued = [a for a in assignments if a.get("yoyaku_number")]
        not_issued = [a for a in assignments if not a.get("yoyaku_number")]

        if not not_issued:
            print(f"  全 {len(issued)} 件の予約番号を取得しました。")
            break

        print(f"  予約番号取得: {len(issued)} 件 / 未発行: {len(not_issued)} 件")

        if attempt < max_retries:
            retry_min = retry_interval // 60
            print(f"  {retry_min} 分後に再取得します...")
            time.sleep(retry_interval)

    # ── Step 8: 割り当てシートに予約番号・有効期限を更新 ──
    issued = [a for a in assignments if a.get("yoyaku_number")]
    not_issued = [a for a in assignments if not a.get("yoyaku_number")]

    if issued:
        print(f"\n[Step 8] スプレッドシートを更新中...")
        update_reservation_info(issued)

    # ── Step 9: メール送信 ────────────────────────
    if issued:
        print(f"\n[Step 9] 予約番号取得済み {len(issued)} 件にメールを送信中...")
        send_gmail(issued)

    if not_issued:
        print(f"\n⚠️ 未発行 {len(not_issued)} 件は retry_send.py で後から再送できます:")
        for a in not_issued:
            print(f"   - SIM {a.get('sim_phone', '')}")

    # ── Step 10: タスクを完了に更新 ──────────────────
    task["status"] = "completed"
    task["completed_at"] = datetime.now().isoformat()
    save_config(config)

    print("\n" + "=" * 55)
    print("  再割り当て処理が完了しました")
    print(f"  完了日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)


if __name__ == "__main__":
    main()
