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
    records = read_spreadsheet_data()
    if not records:
        print("データが見つかりませんでした。処理を終了します。")
        return
    print(f"         {len(records)} 件のデータを読み込みました")

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

    # ── Step 3.5: 処理済みフラグを更新 ───────────────────
    print("\n[Step 3.5] 申込スプレッドシートの処理済みフラグを更新中...")
    processed_records = list({
        a["record"].get("_row_number"): a["record"]
        for a in assignments
        if a["record"].get("_row_number")
    }.values())
    mark_as_processed(processed_records)

    # ── Step 4: 待機 ─────────────────────────────────────
    wait_min = delay_seconds // 60
    print(f"\n[Step 4] {wait_min} 分後に予約番号を取得します...")
    print(f"         (Ctrl+C でキャンセル可能)")
    time.sleep(delay_seconds)

    # ── Step 5: 予約番号・有効期限を取得 ─────────────────
    print("\n[Step 5] jpmob から予約番号・有効期限を取得中...")
    assignments = fetch_reservations(assignments)

    # ── Step 6: 管理スプレッドシートを更新 ───────────────
    print("\n[Step 6] 管理スプレッドシートを更新中...")
    update_reservation_info(assignments)

    # ── Step 7: メール送信 ────────────────────────────────
    print("\n[Step 7] 各顧客にメールを送信中...")
    send_gmail(assignments)

    print("\n" + "=" * 55)
    print("  全処理が完了しました")
    print(f"  完了日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)


if __name__ == "__main__":
    main()
