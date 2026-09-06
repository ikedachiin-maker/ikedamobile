"""
申し込み管理タブと決済照合キュー。

専用フォームの申込情報は「申し込み管理」に記録する。
決済照合キューは、決済成功後にシート登録が一時的に失敗しても
申込情報を失わず、後続の自動照合で安全に回収するために使用する。
"""

import os
from datetime import datetime, timedelta, timezone

import gspread
from dotenv import load_dotenv

from sheets_reader import get_credentials

load_dotenv()

APPLICATION_SHEET_NAME = "申し込み管理"
RECONCILIATION_SHEET_NAME = "決済照合キュー"

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
    "予約番号案内",
]

RECONCILIATION_HEADERS = [
    "決済ID",
    "状態",
    "申込ID",
    "決済日時",
    "更新日時",
    "メールアドレス",
    "プラン",
    "申込回線数",
    "決済金額",
    "申込データ",
    "エラー詳細",
]

_app_worksheet_cache: gspread.Worksheet | None = None
JST = timezone(timedelta(hours=9), name="JST")


def _now_jst() -> str:
    return datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")


def _open_sheet(sheet_name: str, headers: list[str]) -> gspread.Worksheet:
    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    if not spreadsheet_id:
        raise RuntimeError("SPREADSHEET_ID が設定されていません")

    client = gspread.authorize(get_credentials())
    spreadsheet = client.open_by_key(spreadsheet_id)

    try:
        worksheet = spreadsheet.worksheet(sheet_name)
        print(f"[application_sheet] 既存の '{sheet_name}' タブを使用します")
    except gspread.exceptions.WorksheetNotFound:
        print(f"[application_sheet] '{sheet_name}' タブを新規作成します...")
        worksheet = spreadsheet.add_worksheet(
            title=sheet_name,
            rows=1000,
            cols=len(headers),
        )
        worksheet.append_row(headers, value_input_option="USER_ENTERED")
        worksheet.format(
            "1:1",
            {
                "textFormat": {"bold": True},
                "backgroundColor": {"red": 0.82, "green": 0.91, "blue": 0.97},
            },
        )
        print(f"[application_sheet] '{sheet_name}' タブを作成しました")

    return worksheet


def _column_name(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _record_from_row(headers: list[str], row: list[str]) -> dict:
    return {
        header: row[index] if index < len(row) else ""
        for index, header in enumerate(headers)
    }


def _find_row_by_value(
    worksheet: gspread.Worksheet,
    headers: list[str],
    header: str,
    value: str,
) -> tuple[int, dict] | None:
    if not value:
        return None

    column_index = headers.index(header)
    rows = worksheet.get_all_values()
    for row_number, row in enumerate(rows[1:], start=2):
        if column_index < len(row) and row[column_index].strip() == value:
            return row_number, _record_from_row(headers, row)
    return None


def get_or_create_application_sheet() -> gspread.Worksheet:
    global _app_worksheet_cache
    _app_worksheet_cache = _open_sheet(APPLICATION_SHEET_NAME, HEADERS)
    return _app_worksheet_cache


def get_or_create_reconciliation_sheet() -> gspread.Worksheet:
    return _open_sheet(RECONCILIATION_SHEET_NAME, RECONCILIATION_HEADERS)


def append_application_record(record: dict) -> bool:
    """
    申し込み管理に1行追加する。

    同じ決済IDがすでにあれば追記しない。True は新規追加、
    False はすでに登録済みであることを表す。
    """
    worksheet = get_or_create_application_sheet()
    payment_id = str(record.get("決済ID", "")).strip()

    if payment_id and _find_row_by_value(worksheet, HEADERS, "決済ID", payment_id):
        print(f"[application_sheet] 決済IDは登録済みのためスキップ: {payment_id}")
        return False

    row = [str(record.get(header, "")) for header in HEADERS]
    worksheet.append_row(row, value_input_option="USER_ENTERED")
    print(f"[application_sheet] 申し込みを記録しました: payment_id={payment_id}")
    return True


def application_record_exists(payment_id: str) -> bool:
    worksheet = get_or_create_application_sheet()
    return _find_row_by_value(worksheet, HEADERS, "決済ID", payment_id) is not None


def get_reconciliation_record(payment_id: str) -> dict | None:
    worksheet = get_or_create_reconciliation_sheet()
    found = _find_row_by_value(
        worksheet,
        RECONCILIATION_HEADERS,
        "決済ID",
        payment_id,
    )
    return found[1] if found else None


def upsert_reconciliation_record(record: dict) -> None:
    """決済IDをキーに、照合キューを新規追加または更新する。"""
    worksheet = get_or_create_reconciliation_sheet()
    payment_id = str(record.get("決済ID", "")).strip()
    if not payment_id:
        raise ValueError("決済IDがないため照合キューを更新できません")

    found = _find_row_by_value(
        worksheet,
        RECONCILIATION_HEADERS,
        "決済ID",
        payment_id,
    )
    if found:
        row_number, current = found
        row = [
            str(record.get(header, current.get(header, "")))
            for header in RECONCILIATION_HEADERS
        ]
        end_column = _column_name(len(RECONCILIATION_HEADERS))
        worksheet.update(
            range_name=f"A{row_number}:{end_column}{row_number}",
            values=[row],
        )
        return

    row = [str(record.get(header, "")) for header in RECONCILIATION_HEADERS]
    worksheet.append_row(row, value_input_option="USER_ENTERED")
    print(f"[application_sheet] 決済照合キューを追加しました: payment_id={payment_id}")


def set_reconciliation_status(
    payment_id: str,
    status: str,
    error_detail: str = "",
) -> None:
    record = get_reconciliation_record(payment_id)
    if record is None:
        raise LookupError(f"決済照合キューに見つかりません: {payment_id}")

    record["状態"] = status
    record["更新日時"] = _now_jst()
    if error_detail:
        record["エラー詳細"] = error_detail
    upsert_reconciliation_record(record)


def reconciliation_status_summary() -> dict[str, int]:
    worksheet = get_or_create_reconciliation_sheet()
    rows = worksheet.get_all_values()[1:]
    status_index = RECONCILIATION_HEADERS.index("状態")
    summary: dict[str, int] = {}

    for row in rows:
        status = row[status_index].strip() if status_index < len(row) else ""
        summary[status or "未設定"] = summary.get(status or "未設定", 0) + 1

    return summary


def read_unprocessed_applications() -> list[dict]:
    """
    「申し込み管理」タブから未処理の申し込みを取得する。
    「予約番号案内」列が空のレコードのみ返す。
    """
    worksheet = get_or_create_application_sheet()
    rows = worksheet.get_all_values()

    unprocessed = []
    for row_number, row in enumerate(rows[1:], start=2):
        record = _record_from_row(HEADERS, row)
        if not record.get("予約番号案内"):
            record["_row_number"] = row_number
            record["_source"] = "application_sheet"
            unprocessed.append(record)

    print(
        f"[application_sheet] 申し込み管理: "
        f"全 {max(0, len(rows) - 1)} 件中、未処理 {len(unprocessed)} 件"
    )
    return unprocessed


def mark_applications_processed(records: list[dict]) -> None:
    """処理完了した申し込みの「予約番号案内」列に TRUE を書き込む。"""
    global _app_worksheet_cache

    if not _app_worksheet_cache:
        print("[application_sheet] ワークシートが未初期化のためスキップします")
        return

    column_index = HEADERS.index("予約番号案内") + 1
    seen_rows: set[int] = set()

    for record in records:
        row_number = record.get("_row_number")
        if row_number and row_number not in seen_rows:
            _app_worksheet_cache.update_cell(row_number, column_index, "TRUE")
            seen_rows.add(row_number)

    print(f"[application_sheet] {len(seen_rows)} 件を処理済みに更新しました")
