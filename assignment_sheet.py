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
    "フリガナ",
    "性別",
]


ASSIGNMENT_SHEET_NAME = "割り当て"


def get_or_create_assignment_sheet() -> gspread.Worksheet:
    """既存スプレッドシート内の「割り当て」タブを取得または新規作成する"""
    creds = get_credentials()
    client = gspread.authorize(creds)

    spreadsheet_id = os.getenv("SPREADSHEET_ID", "")
    if not spreadsheet_id:
        raise ValueError("SPREADSHEET_ID が .env に設定されていません")

    spreadsheet = client.open_by_key(spreadsheet_id)

    # 「割り当て」シートが存在するか確認
    try:
        worksheet = spreadsheet.worksheet(ASSIGNMENT_SHEET_NAME)
        print(f"[割り当てSheet] 既存タブを使用: {ASSIGNMENT_SHEET_NAME}")
        return worksheet
    except gspread.exceptions.WorksheetNotFound:
        pass

    # タブを新規作成してヘッダーを書き込む
    worksheet = spreadsheet.add_worksheet(title=ASSIGNMENT_SHEET_NAME, rows=1000, cols=len(HEADERS))
    worksheet.append_row(HEADERS)
    print(f"[割り当てSheet] 新規タブ「{ASSIGNMENT_SHEET_NAME}」を作成しました")
    return worksheet


def _ensure_headers(worksheet: gspread.Worksheet) -> None:
    """既存シートのヘッダーに不足列があれば列数を拡張してから追加する"""
    existing = worksheet.row_values(1)
    missing = [h for h in HEADERS if h not in existing]
    if missing:
        needed_cols = len(existing) + len(missing)
        if worksheet.col_count < needed_cols:
            worksheet.resize(cols=needed_cols)
        start_col = len(existing) + 1
        for i, h in enumerate(missing):
            worksheet.update_cell(1, start_col + i, h)
        print(f"[割り当てSheet] ヘッダー追加: {', '.join(missing)}")


def write_assignments(assignments: list[dict]) -> None:
    """割り当て情報をスプレッドシートに書き込む"""
    worksheet = get_or_create_assignment_sheet()
    _ensure_headers(worksheet)

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
            f"{record.get('姓（フリガナ）', '')} {record.get('名（フリガナ）', '')}".strip(),
            record.get("性別", ""),
        ])

    if rows:
        worksheet.append_rows(rows)
        print(f"[割り当てSheet] {len(rows)} 件を書き込みました")


def get_processed_card_ids() -> set[str]:
    """
    割り当てシートに既に記録されているカードIDのセットを返す。
    input_to_jpmob() が二重処理を防ぐために使用する。
    """
    try:
        worksheet  = get_or_create_assignment_sheet()
        all_rows   = worksheet.get_all_values()
        col        = HEADERS.index("カードID")
        ids = {
            row[col]
            for row in all_rows[1:]   # ヘッダー行をスキップ
            if len(row) > col and row[col]
        }
        print(f"[割り当てSheet] 既処理済みカードID: {len(ids)} 件")
        return ids
    except Exception as e:
        print(f"[割り当てSheet] 既処理済みカードID取得エラー（空セットで続行）: {e}")
        return set()


def get_assignments_by_phones(phones: list[str]) -> list[dict]:
    """
    割り当てシートから指定したSIM電話番号に一致する行を取得する。
    Returns: [{"顧客名": ..., "メールアドレス": ..., "カードID": ..., ...}, ...]
    """
    worksheet = get_or_create_assignment_sheet()
    all_rows = worksheet.get_all_values()
    if len(all_rows) <= 1:
        return []

    phone_col = HEADERS.index("SIM電話番号")
    phone_set = set(phones)
    results = []

    for row in all_rows[1:]:
        row_dict = dict(zip(HEADERS, row + [""] * (len(HEADERS) - len(row))))
        if row_dict.get("SIM電話番号", "").strip() in phone_set:
            results.append(row_dict)

    print(f"[割り当てSheet] 電話番号検索: {len(results)} 件ヒット（検索 {len(phones)} 件）")
    return results


def update_sim_assignment(old_phone: str, new_phone: str, new_card_id: str, new_entered_at: str) -> bool:
    """
    割り当てシートの既存行のSIM情報を差し替える。
    old_phone の行を見つけて、新しいSIM電話番号・カードID・入力日時に更新し、
    予約番号・有効期限をクリアする。
    """
    worksheet = get_or_create_assignment_sheet()
    all_rows = worksheet.get_all_values()
    if len(all_rows) <= 1:
        return False

    phone_col     = HEADERS.index("SIM電話番号") + 1      # 1-indexed
    card_id_col   = HEADERS.index("カードID") + 1
    entered_col   = HEADERS.index("入力日時") + 1
    yoyaku_col    = HEADERS.index("予約番号") + 1
    expiry_col    = HEADERS.index("有効期限") + 1
    sent_col      = HEADERS.index("メール送信済み") + 1

    for row_idx, row in enumerate(all_rows[1:], start=2):
        row_dict = dict(zip(HEADERS, row + [""] * (len(HEADERS) - len(row))))
        if row_dict.get("SIM電話番号", "").strip() == old_phone:
            worksheet.update_cell(row_idx, phone_col, new_phone)
            worksheet.update_cell(row_idx, card_id_col, new_card_id)
            worksheet.update_cell(row_idx, entered_col, new_entered_at)
            worksheet.update_cell(row_idx, yoyaku_col, "")
            worksheet.update_cell(row_idx, expiry_col, "")
            worksheet.update_cell(row_idx, sent_col, "未送信")
            print(f"[割り当てSheet] SIM差し替え: {old_phone} → {new_phone} (card_id={new_card_id})")
            return True

    print(f"[割り当てSheet] SIM差し替え失敗: {old_phone} が見つかりません")
    return False


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
