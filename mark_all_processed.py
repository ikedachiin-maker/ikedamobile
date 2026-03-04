"""
既存の全レコードを「処理済み」にする一回限りのユーティリティスクリプト。
初回セットアップ時など、すでに手動で処理済みのデータに対して実行する。
"""
import os
import gspread
from dotenv import load_dotenv
from sheets_reader import get_credentials

load_dotenv()


def mark_all_as_processed():
    creds = get_credentials()
    client = gspread.authorize(creds)

    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    sheet_name = os.getenv("SHEET_NAME", "Sheet1")
    status_col = os.getenv("STATUS_COLUMN", "処理済み")

    spreadsheet = client.open_by_key(spreadsheet_id)
    worksheet = spreadsheet.worksheet(sheet_name)

    headers = worksheet.row_values(1)
    if status_col not in headers:
        print(f"'{status_col}' 列が見つかりません。スプレッドシートに列を追加してください。")
        return

    col_idx = headers.index(status_col) + 1  # 1-indexed
    col_letter = chr(ord("A") + col_idx - 1)

    all_records = worksheet.get_all_records()

    # 未処理（空）の行だけを対象にする
    target_rows = []
    for i, record in enumerate(all_records, start=2):
        if not record.get(status_col):
            name = record.get("名前", f"行{i}")
            target_rows.append((i, name))

    if not target_rows:
        print("未処理のレコードはありませんでした。")
        return

    print(f"{len(target_rows)} 件を更新します...")

    # 対象行だけを個別セル指定で一括更新（既存のTRUEは上書きしない）
    updates = [
        {
            "range": f"{col_letter}{row}",
            "values": [["TRUE"]]
        }
        for row, _ in target_rows
    ]
    worksheet.batch_update(updates)

    for _, name in target_rows:
        print(f"  処理済みに更新: {name}")

    print(f"\n完了: {len(target_rows)} 件を処理済みに更新しました")


if __name__ == "__main__":
    mark_all_as_processed()
