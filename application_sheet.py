"""
申し込み管理タブ

専用フォームからの申し込みを SPREADSHEET_ID 内の「申し込み管理」タブに記録し、
main.py からも未処理レコードとして読み込めるようにする。

タブが存在しない場合は自動で作成する。
"""

import os
import gspread
from dotenv import load_dotenv
from sheets_reader import get_credentials

load_dotenv()

APPLICATION_SHEET_NAME = "申し込み管理"

# タブのヘッダー列（順序固定）
HEADERS = [
    "タイムスタンプ",
    "姓（漢字）",
    "名（漢字）",
    "姓（フリガナ）",
    "名（フリガナ）",
    "生年月日",
    "性別",
    "メールアドレス",
    "プラン",
    "申込回線数",
    "決済金額",
    "決済ID",
    "本人確認書類",
    "予約番号案内",   # ← 空 = 未処理 / TRUE = 処理済み（main.py と共通）
]

_app_worksheet_cache: gspread.Worksheet | None = None


# ─────────────────────────────────────────────
# タブの取得・作成
# ─────────────────────────────────────────────

def get_or_create_application_sheet() -> gspread.Worksheet:
    """
    SPREADSHEET_ID 内の「申し込み管理」タブを開く。
    存在しない場合はヘッダー付きで新規作成する。
    """
    global _app_worksheet_cache

    creds  = get_credentials()
    client = gspread.authorize(creds)

    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    spreadsheet    = client.open_by_key(spreadsheet_id)

    try:
        ws = spreadsheet.worksheet(APPLICATION_SHEET_NAME)
        print(f"[application_sheet] 既存の '{APPLICATION_SHEET_NAME}' タブを使用します")
    except gspread.exceptions.WorksheetNotFound:
        print(f"[application_sheet] '{APPLICATION_SHEET_NAME}' タブを新規作成します...")
        ws = spreadsheet.add_worksheet(
            title=APPLICATION_SHEET_NAME,
            rows=1000,
            cols=len(HEADERS),
        )
        ws.append_row(HEADERS, value_input_option="USER_ENTERED")
        # ヘッダー行を太字・背景色（薄い青）で装飾
        ws.format("1:1", {
            "textFormat":      {"bold": True},
            "backgroundColor": {"red": 0.82, "green": 0.91, "blue": 0.97},
        })
        print(f"[application_sheet] '{APPLICATION_SHEET_NAME}' タブを作成しました")

    _app_worksheet_cache = ws
    return ws


# ─────────────────────────────────────────────
# 新規申し込みの追記
# ─────────────────────────────────────────────

def append_application_record(record: dict) -> None:
    """
    専用フォームからの申し込みを「申し込み管理」タブに1行追加する。
    HEADERS の順に値を並べる（存在しないキーは空文字）。
    """
    ws  = get_or_create_application_sheet()
    row = [str(record.get(h, "")) for h in HEADERS]
    ws.append_row(row, value_input_option="USER_ENTERED")
    print(f"[application_sheet] 申し込みを記録しました: {record.get('メールアドレス', '')}")


# ─────────────────────────────────────────────
# 未処理申し込みの読み込み（main.py から呼び出し）
# ─────────────────────────────────────────────

def read_unprocessed_applications() -> list[dict]:
    """
    「申し込み管理」タブから未処理の申し込みを取得する。
    「予約番号案内」列が空のレコードのみ返す。
    各レコードに以下を付与:
      _row_number : スプレッドシート上の行番号（mark_applications_processed で使用）
      _source     : "application_sheet"（main.py で振り分けに使用）
    """
    global _app_worksheet_cache

    ws = get_or_create_application_sheet()
    _app_worksheet_cache = ws

    all_records = ws.get_all_records()

    unprocessed = []
    for i, rec in enumerate(all_records, start=2):  # 2行目がデータ開始行
        if not rec.get("予約番号案内"):
            rec["_row_number"] = i
            rec["_source"]     = "application_sheet"
            unprocessed.append(rec)

    print(
        f"[application_sheet] 申し込み管理: "
        f"全 {len(all_records)} 件中、未処理 {len(unprocessed)} 件"
    )
    return unprocessed


# ─────────────────────────────────────────────
# 処理済みフラグの更新（main.py から呼び出し）
# ─────────────────────────────────────────────

def mark_applications_processed(records: list[dict]) -> None:
    """
    処理完了した申し込みの「予約番号案内」列に「TRUE」を書き込む。
    各レコードの _row_number を使って行を特定する。
    """
    global _app_worksheet_cache

    if not _app_worksheet_cache:
        print("[application_sheet] ワークシートが未初期化のためスキップします")
        return

    ws = _app_worksheet_cache

    try:
        col_idx = HEADERS.index("予約番号案内") + 1  # 1-indexed
    except ValueError:
        print("[application_sheet] '予約番号案内' 列が HEADERS に見つかりません")
        return

    seen_rows: set[int] = set()
    for rec in records:
        row_num = rec.get("_row_number")
        if row_num and row_num not in seen_rows:
            ws.update_cell(row_num, col_idx, "TRUE")
            seen_rows.add(row_num)

    print(f"[application_sheet] {len(seen_rows)} 件を処理済みに更新しました")
