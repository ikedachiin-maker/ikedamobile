"""Google スプレッドシートからデータを読み込むモジュール"""
import os
import gspread
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from dotenv import load_dotenv

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
]

_worksheet_cache: gspread.Worksheet | None = None


def get_credentials():
    """OAuth2 認証情報を取得または更新する"""
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())

    return creds


def read_spreadsheet_data() -> list[dict]:
    """
    スプレッドシートから未処理のデータを取得する。
    処理済み列（STATUS_COLUMN）が空のレコードのみ返す。
    各レコードに _row_number（スプレッドシート上の行番号）を付与する。
    """
    global _worksheet_cache

    creds = get_credentials()
    client = gspread.authorize(creds)

    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    sheet_name = os.getenv("SHEET_NAME", "Sheet1")
    status_col = os.getenv("STATUS_COLUMN", "処理済み")

    spreadsheet = client.open_by_key(spreadsheet_id)
    worksheet = spreadsheet.worksheet(sheet_name)
    _worksheet_cache = worksheet

    all_records = worksheet.get_all_records()

    # 未処理のレコードのみ抽出（処理済み列が空のもの）
    unprocessed = []
    for i, record in enumerate(all_records, start=2):  # 2行目がデータ開始行
        if not record.get(status_col):
            record["_row_number"] = i
            unprocessed.append(record)

    print(f"[スプレッドシート] 全 {len(all_records)} 件中、未処理 {len(unprocessed)} 件を読み込みました")
    return unprocessed


def mark_as_processed(records: list[dict]) -> None:
    """
    処理完了したレコードのスプレッドシート行に「TRUE」を書き込む。
    各レコードの _row_number を使って行を特定する。
    """
    global _worksheet_cache
    if not _worksheet_cache:
        print("[スプレッドシート] ワークシートが未初期化のためスキップします")
        return

    worksheet = _worksheet_cache
    status_col = os.getenv("STATUS_COLUMN", "処理済み")

    headers = worksheet.row_values(1)
    if status_col not in headers:
        print(f"[スプレッドシート] '{status_col}' 列が見つかりません。スプレッドシートに列を追加してください。")
        return

    col_idx = headers.index(status_col) + 1  # 1-indexed

    seen_rows: set[int] = set()
    for record in records:
        row_num = record.get("_row_number")
        if row_num and row_num not in seen_rows:
            worksheet.update_cell(row_num, col_idx, "TRUE")
            seen_rows.add(row_num)

    print(f"[スプレッドシート] {len(seen_rows)} 件を処理済みに更新しました")
