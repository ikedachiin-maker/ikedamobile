"""
フォームトリガー URL をスプレッドシートに書き込むスクリプト

start_server.sh から呼び出される。
Cloudflare Tunnel 起動後の /form-trigger URL を
スプレッドシートの「config」シートに保存する。

Google Apps Script はこのセルを読み取ることで
毎回 URL を自動取得できる。

使い方:
    python update_trigger_url.py https://xxxx.trycloudflare.com/form-trigger
"""

import sys
import os
import gspread
from dotenv import load_dotenv
from sheets_reader import get_credentials

load_dotenv()

CONFIG_SHEET_NAME = "config"
URL_CELL = "B1"
LABEL_CELL = "A1"


def update_trigger_url(url: str) -> None:
    creds = get_credentials()
    client = gspread.authorize(creds)

    spreadsheet_id = os.getenv("SPREADSHEET_ID")
    spreadsheet = client.open_by_key(spreadsheet_id)

    # config シートがなければ作成
    try:
        sheet = spreadsheet.worksheet(CONFIG_SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=CONFIG_SHEET_NAME, rows=10, cols=2)
        print(f"[config] '{CONFIG_SHEET_NAME}' シートを新規作成しました")

    sheet.update(LABEL_CELL, [["form_trigger_url"]])
    sheet.update(URL_CELL, [[url]])
    print(f"[config] フォームトリガーURL をスプレッドシートに書き込みました: {url}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使い方: python update_trigger_url.py <URL>")
        sys.exit(1)
    update_trigger_url(sys.argv[1])
