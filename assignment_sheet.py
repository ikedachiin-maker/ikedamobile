"""割り当てスプレッドシートを管理するモジュール"""
import os
import gspread
from datetime import datetime
from sheets_reader import get_credentials
from dotenv import load_dotenv

load_dotenv()

HEADERS = [
    "タイムスタンプ",
    "顧客名",
    "メールアドレス",
    "SIM電話番号",
    "カードID",
    "入力日時",
    "予約番号",
    "有効期限",
    "メール送信済み",
]


def get_or_create_assignment_sheet() -> gspread.Worksheet:
    """割り当て管理スプレッドシートを取得または新規作成する"""
    creds = get_credentials()
    client = gspread.authorize(creds)

    sheet_id = os.getenv("ASSIGNMENT_SPREADSHEET_ID", "")

    if sheet_id:
        try:
            spreadsheet = client.open_by_key(sheet_id)
            print(f"[割り当てSheet] 既存シートを使用: {spreadsheet.title}")
            return spreadsheet.sheet1
        except Exception:
            print("[割り当てSheet] 既存シートが見つからないため新規作成します")

    # 新規スプレッドシートを作成
    spreadsheet = client.create("jpmob割り当て管理")
    worksheet = spreadsheet.sheet1
    worksheet.update_title("割り当て")

    # ヘッダー行を書き込む
    worksheet.append_row(HEADERS)

    print(f"[割り当てSheet] 新規スプレッドシートを作成しました")
    print(f"[割り当てSheet] SpreadsheetID: {spreadsheet.id}")
    print(f"[割り当てSheet] .env に以下を追加してください:")
    print(f"  ASSIGNMENT_SPREADSHEET_ID={spreadsheet.id}")

    return worksheet


def write_assignments(assignments: list[dict]) -> None:
    """割り当て情報をスプレッドシートに書き込む"""
    worksheet = get_or_create_assignment_sheet()

    rows = []
    for a in assignments:
        record = a["record"]
        rows.append([
            record.get("タイムスタンプ", ""),
            f"{record.get('姓（漢字）', '')} {record.get('名（漢字）', '')}".strip(),
            record.get("メールアドレス", ""),
            a.get("sim_phone", ""),
            a.get("card_id", ""),
            a.get("entered_at", ""),
            "",   # 予約番号（後で更新）
            "",   # 有効期限（後で更新）
            "未送信",
        ])

    if rows:
        worksheet.append_rows(rows)
        print(f"[割り当てSheet] {len(rows)} 件を書き込みました")


def update_reservation_info(assignments: list[dict]) -> None:
    """予約番号・有効期限をスプレッドシートに更新する"""
    worksheet = get_or_create_assignment_sheet()

    all_rows = worksheet.get_all_values()
    if len(all_rows) <= 1:
        return  # ヘッダーのみ

    # カードIDで行を検索して更新
    card_id_col = HEADERS.index("カードID") + 1        # 1-indexed
    yoyaku_col  = HEADERS.index("予約番号") + 1
    expiry_col  = HEADERS.index("有効期限") + 1
    sent_col    = HEADERS.index("メール送信済み") + 1

    for a in assignments:
        card_id = a.get("card_id", "")
        yoyaku  = a.get("yoyaku_number", "")
        expiry  = a.get("expiry_date", "")

        for row_idx, row in enumerate(all_rows[1:], start=2):  # skip header
            if len(row) >= card_id_col and row[card_id_col - 1] == card_id:
                worksheet.update_cell(row_idx, yoyaku_col, yoyaku)
                worksheet.update_cell(row_idx, expiry_col, expiry)
                worksheet.update_cell(row_idx, sent_col, "送信済み")
                print(f"[割り当てSheet] カードID {card_id} を更新しました")
                break
