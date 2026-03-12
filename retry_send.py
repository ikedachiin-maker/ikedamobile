"""
retry_send.py — 予約番号未発行のSIMに対して再取得・メール再送を行うスクリプト

使い方:
    python retry_send.py

割り当て管理スプレッドシートから「予約番号が空欄」のレコードを読み込み、
jpmob から予約番号を取得してメールを再送します。
"""

import os
from datetime import datetime
from dotenv import load_dotenv

import gspread
from sheets_reader import get_credentials
from jpmob_automator import fetch_reservations
from gmail_sender import send_gmail
from assignment_sheet import (
    get_or_create_assignment_sheet,
    update_reservation_info,
    HEADERS,
)

load_dotenv()


def read_pending_assignments() -> list[dict]:
    """予約番号が空欄のアサインレコードを読み込む"""
    worksheet = get_or_create_assignment_sheet()
    all_rows = worksheet.get_all_values()

    if len(all_rows) <= 1:
        print("割り当てシートにデータがありません。")
        return []

    headers = all_rows[0]
    pending = []

    for row in all_rows[1:]:
        row_dict = dict(zip(headers, row + [""] * (len(headers) - len(row))))

        yoyaku = row_dict.get("予約番号", "").strip()
        card_id = row_dict.get("カードID", "").strip()

        if not card_id:
            continue

        if not yoyaku:
            # メールアドレスと名前を復元
            email = row_dict.get("メールアドレス", "").strip()
            sim_phone = row_dict.get("SIM電話番号", "").strip()
            name = row_dict.get("顧客名", "").strip()

            # record を再構築（gmail_sender が必要とするキー）
            name_parts = name.split(" ", 1) if " " in name else [name, ""]
            record = {
                "名前": name,
                "姓（漢字）": name_parts[0],
                "名（漢字）": name_parts[1] if len(name_parts) > 1 else "",
                "メールアドレス": email,
            }

            pending.append({
                "card_id": card_id,
                "sim_phone": sim_phone,
                "yoyaku_number": "",
                "expiry_date": "",
                "record": record,
            })
            print(f"  対象: {name} ({email}) — SIM {sim_phone} (card_id={card_id})")

    return pending


def main():
    print("=" * 55)
    print("  予約番号 再取得・メール再送スクリプト")
    print(f"  実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    print("\n[Step 1] 予約番号未発行のレコードを確認中...")
    assignments = read_pending_assignments()

    if not assignments:
        print("予約番号未発行のレコードはありません。処理を終了します。")
        return

    print(f"         {len(assignments)} 件が対象です。")

    print("\n[Step 2] jpmob から予約番号を取得中...")
    assignments = fetch_reservations(assignments)

    issued = [a for a in assignments if a.get("yoyaku_number")]
    not_issued = [a for a in assignments if not a.get("yoyaku_number")]

    print(f"\n  予約番号取得: {len(issued)} 件 / 未発行: {len(not_issued)} 件")

    if not issued:
        print("\njpmob がまだ予約番号を発行していません。しばらく待ってから再実行してください。")
        return

    print("\n[Step 3] スプレッドシートを更新中...")
    update_reservation_info(issued)

    print("\n[Step 4] メールを送信中...")
    send_gmail(issued)

    if not_issued:
        print(f"\n⚠️  {len(not_issued)} 件はまだ予約番号が未発行です:")
        for a in not_issued:
            print(f"   - {a['record'].get('名前', '')} / SIM {a['sim_phone']}")
        print("   → 再度 python retry_send.py を実行してください。")

    print("\n" + "=" * 55)
    print("  再送処理が完了しました")
    print(f"  完了日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)


if __name__ == "__main__":
    main()
