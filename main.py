"""
jpmob 自動入力ツール — メインスクリプト

業務フロー:
  1. スプレッドシートからデータ読み込み
  2. [8:00〜20:00 のみ] jpmob の開通済みSIMカードに顧客情報を入力
  3. 割り当て情報を管理スプレッドシートに記録
  4. 約1時間待機
  5. jpmob から予約番号・有効期限を取得
  6. 管理スプレッドシートを更新
  7. 各顧客にメール送信
"""

import time
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

from sheets_reader import read_spreadsheet_data, mark_as_processed
from application_sheet import read_unprocessed_applications, mark_applications_processed
from jpmob_automator import input_to_jpmob, fetch_reservations
from gmail_sender import send_gmail
from assignment_sheet import write_assignments, update_reservation_info

load_dotenv()


# ─────────────────────────────────────────────
# 時間制限チェック（8:00〜20:00 のみ実行）
# ─────────────────────────────────────────────

def wait_until_operational_hours() -> None:
    """8:00〜20:00 の間だけ処理を実行する。範囲外の場合は次の 8:00 まで待機。"""
    while True:
        now = datetime.now()
        hour = now.hour

        if 8 <= hour < 20:
            return  # 実行可能時間帯

        if hour >= 20:
            # 翌日 8:00 まで待機
            next_start = (now + timedelta(days=1)).replace(
                hour=8, minute=0, second=0, microsecond=0
            )
        else:
            # 当日 8:00 まで待機
            next_start = now.replace(hour=8, minute=0, second=0, microsecond=0)

        wait_sec = (next_start - now).total_seconds()
        wait_min = int(wait_sec // 60)
        print(
            f"[時間制限] 現在 {now.strftime('%H:%M')} — "
            f"入力は 8:00〜20:00 のみ実行可能です。\n"
            f"           {next_start.strftime('%Y-%m-%d %H:%M')} まで約 {wait_min} 分待機します..."
        )
        # 最大 60 秒ごとに再チェック（長時間スリープを避ける）
        time.sleep(min(wait_sec, 60))


# ─────────────────────────────────────────────
# メイン処理
# ─────────────────────────────────────────────

def main() -> None:
    delay_seconds = int(os.getenv("SEND_DELAY_SECONDS", "3600"))

    print("=" * 55)
    print("  jpmob 自動入力ツール 開始")
    print(f"  実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    # ── Step 1: スプレッドシートからデータ読み込み ──────────
    print("\n[Step 1] スプレッドシートからデータを読み込み中...")

    # ① 既存の Google フォーム回答シート
    gform_records = read_spreadsheet_data()

    # ② 専用フォームの「申し込み管理」タブ
    app_records = read_unprocessed_applications()

    # ── 重複チェック（メールアドレスで同一人物を検出）──────
    # 専用フォーム（構造化データ）を優先し、Googleフォーム側の重複を除外する
    all_records = gform_records + app_records
    seen_emails: dict[str, dict] = {}
    records: list[dict] = []
    duplicates_removed = 0

    # 専用フォームを先に処理（優先度が高い）
    for rec in app_records + gform_records:
        email = (rec.get("メールアドレス") or "").strip().lower()
        if not email:
            # メールアドレスがないレコードはそのまま通す
            records.append(rec)
            continue
        if email in seen_emails:
            prev = seen_emails[email]
            prev_src = "専用フォーム" if prev.get("_source") == "application_sheet" else "Googleフォーム"
            cur_src  = "専用フォーム" if rec.get("_source") == "application_sheet" else "Googleフォーム"
            name = f"{rec.get('姓（漢字）', '')} {rec.get('名（漢字）', '')}".strip() \
                   or rec.get("名前", "")
            print(
                f"  ⚠️ 重複検出（スキップ）: {name} <{email}> "
                f"— {cur_src}のレコードを除外（{prev_src}を優先）"
            )
            duplicates_removed += 1
            continue
        seen_emails[email] = rec
        records.append(rec)

    if duplicates_removed:
        print(f"  → {duplicates_removed} 件の重複を除外しました")

    if not records:
        print("処理対象のデータが見つかりませんでした。処理を終了します。")
        return
    print(
        f"         合計 {len(records)} 件を読み込みました "
        f"（Googleフォーム: {len(gform_records)} 件 / 専用フォーム: {len(app_records)} 件"
        f"{f' / 重複除外: {duplicates_removed} 件' if duplicates_removed else ''}）"
    )

    # ── Step 2: 時間チェック → jpmob 入力 ─────────────────
    print("\n[Step 2] 時間チェック中...")
    wait_until_operational_hours()

    print("\n[Step 2] jpmob への自動入力を開始します...")
    assignments = input_to_jpmob(records)
    if not assignments:
        print("入力できるカードがありませんでした。処理を終了します。")
        return

    # ── Step 3: 割り当て情報をスプレッドシートに記録 ────────
    print("\n[Step 3] 割り当て情報をスプレッドシートに記録中...")
    write_assignments(assignments)

    # ── Step 3.5: 処理済みフラグを更新（ソース別に振り分け）──
    print("\n[Step 3.5] 申込スプレッドシートの処理済みフラグを更新中...")
    assigned_records = list({
        a["record"].get("_row_number"): a["record"]
        for a in assignments
        if a["record"].get("_row_number")
    }.values())

    # Google フォーム回答シートの処理済みフラグ
    gform_done = [r for r in assigned_records if r.get("_source") != "application_sheet"]
    if gform_done:
        mark_as_processed(gform_done)

    # 専用フォーム「申し込み管理」タブの処理済みフラグ
    app_done = [r for r in assigned_records if r.get("_source") == "application_sheet"]
    if app_done:
        mark_applications_processed(app_done)

    # ── Step 4〜7: 予約番号取得 → メール送信（リトライ付き）──
    retry_interval = int(os.getenv("RETRY_INTERVAL_SECONDS", "1800"))  # 30分
    max_retries = int(os.getenv("MAX_RETRIES", "6"))  # 最大6回（計3時間）

    wait_min = delay_seconds // 60
    print(f"\n[Step 4] {wait_min} 分後に予約番号を取得します...")
    print(f"         (Ctrl+C でキャンセル可能)")
    time.sleep(delay_seconds)

    for attempt in range(1, max_retries + 1):
        # ── Step 5: 予約番号・有効期限を取得 ─────────────
        print(f"\n[Step 5] jpmob から予約番号・有効期限を取得中... (試行 {attempt}/{max_retries})")
        assignments = fetch_reservations(assignments)

        issued = [a for a in assignments if a.get("yoyaku_number")]
        not_issued = [a for a in assignments if not a.get("yoyaku_number")]

        if not not_issued:
            print(f"         全 {len(issued)} 件の予約番号を取得しました。")
            break

        print(f"         予約番号取得: {len(issued)} 件 / 未発行: {len(not_issued)} 件")

        if attempt < max_retries:
            retry_min = retry_interval // 60
            print(f"         {retry_min} 分後に再取得します...")
            time.sleep(retry_interval)
        else:
            print(f"         ⚠️ {max_retries} 回試行しましたが未発行のSIMがあります。")

    # ── Step 6: 管理スプレッドシートを更新 ───────────────
    print("\n[Step 6] 管理スプレッドシートを更新中...")
    update_reservation_info(assignments)

    # ── Step 7: 予約番号が取得できたもののみメール送信 ───
    issued = [a for a in assignments if a.get("yoyaku_number")]
    not_issued = [a for a in assignments if not a.get("yoyaku_number")]

    if issued:
        print(f"\n[Step 7] 予約番号取得済み {len(issued)} 件にメールを送信中...")
        send_gmail(issued)
    else:
        print("\n[Step 7] 予約番号が取得できたSIMがありません。メール送信をスキップします。")

    if not_issued:
        print(f"\n⚠️  未発行 {len(not_issued)} 件は後で retry_send.py で再送できます:")
        for a in not_issued:
            print(f"   - {a['record'].get('名前', '')} / SIM {a.get('sim_phone', '')}")

    print("\n" + "=" * 55)
    print("  全処理が完了しました")
    print(f"  完了日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)


if __name__ == "__main__":
    main()
