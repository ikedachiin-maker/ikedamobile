"""Google スプレッドシートからデータを読み込むモジュール"""
import os
import json
import tempfile
import gspread
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from dotenv import load_dotenv

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/drive.file",
]

_worksheet_cache: gspread.Worksheet | None = None

# スクリプトの絶対パスを基準にする（Railway / Mac 両対応）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _extract_json(raw: str) -> str:
    """
    環境変数から最初の有効な JSON オブジェクトだけを抽出する。
    Railway の環境変数に余分な文字（改行・空白・重複ペースト等）が
    含まれていても安全にパースできるようにする。
    """
    decoder = json.JSONDecoder()
    obj, _ = decoder.raw_decode(raw.strip())
    return json.dumps(obj)


def _resolve_credential_paths() -> tuple[str, str]:
    """
    credentials.json / token.json のパスを解決する。
    ローカルファイルが存在する場合はそちらを優先。
    存在しない場合は環境変数 GOOGLE_CREDENTIALS_JSON / GOOGLE_TOKEN_JSON から
    一時ファイルを生成して返す（Railway デプロイ対応）。
    """
    tmp_dir = tempfile.gettempdir()

    # credentials.json
    local_creds = os.path.join(_SCRIPT_DIR, "credentials.json")
    if os.path.exists(local_creds):
        creds_path = local_creds
    else:
        creds_path = os.path.join(tmp_dir, "credentials.json")
        cred_env = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
        if cred_env:
            cleaned = _extract_json(cred_env)
            with open(creds_path, "w") as f:
                f.write(cleaned)

    # token.json
    local_token = os.path.join(_SCRIPT_DIR, "token.json")
    if os.path.exists(local_token):
        token_path = local_token
    else:
        token_path = os.path.join(tmp_dir, "token.json")
        token_env = os.getenv("GOOGLE_TOKEN_JSON", "").strip()
        if token_env:
            cleaned = _extract_json(token_env)
            with open(token_path, "w") as f:
                f.write(cleaned)

    return creds_path, token_path


def get_credentials():
    """OAuth2 認証情報を取得または更新する（ローカル・Railway 両対応）"""
    creds_path, token_path = _resolve_credential_paths()

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Railway 環境ではブラウザが使えないため、token.json を環境変数で渡す必要がある
            if not os.path.exists(creds_path):
                raise RuntimeError(
                    "credentials.json が見つかりません。"
                    "GOOGLE_CREDENTIALS_JSON 環境変数を設定してください。"
                )
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as token:
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


def append_new_record(record: dict) -> None:
    """
    専用フォームからの新規申し込みをスプレッドシートに追記する。
    ヘッダー行の列順に合わせて値を並べる（存在しない列は空文字）。
    """
    global _worksheet_cache

    creds  = get_credentials()
    client = gspread.authorize(creds)

    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    sheet_name     = os.getenv("SHEET_NAME", "Sheet1")

    spreadsheet = client.open_by_key(spreadsheet_id)
    worksheet   = spreadsheet.worksheet(sheet_name)
    _worksheet_cache = worksheet

    headers = worksheet.row_values(1)
    row     = [str(record.get(h, "")) for h in headers]
    worksheet.append_row(row, value_input_option="USER_ENTERED")

    print(f"[スプレッドシート] 新規レコードを追記しました: {record.get('メールアドレス', '')}")
