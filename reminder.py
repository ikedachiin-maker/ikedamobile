"""
フォーム記入忘れリマインダーモジュール

■ 仕組み:
  1. Stripe から支払い済み顧客のメールアドレスを取得
  2. Google フォーム回答スプレッドシートと照合
  3. 支払い済みだがフォーム未記入の顧客にリマインダーメールを送信
  4. 48時間以上経過した場合は2回目のリマインダーを送信

■ 使い方:
  python reminder.py              # 手動実行（リマインダーチェック）
  python reminder.py --send-form  # フォームURLをすぐに送信（支払い確認後に実行）
"""
import os
import sys
import json
import base64
import stripe
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

import gspread
from googleapiclient.discovery import build
from dotenv import load_dotenv
from sheets_reader import get_credentials

load_dotenv()

# ─── 定数 ─────────────────────────────────────────────
FORM_URL         = os.getenv("GOOGLE_FORM_URL", "")          # 登録フォームのURL
REMINDER_HOURS_1 = int(os.getenv("REMINDER_HOURS_1", "24"))  # 1回目リマインダー（時間後）
REMINDER_HOURS_2 = int(os.getenv("REMINDER_HOURS_2", "48"))  # 2回目リマインダー（時間後）
EMAIL_COLUMN     = os.getenv("GMAIL_EMAIL_COLUMN", "メールアドレス")
GMAIL_SENDER     = os.getenv("GMAIL_SENDER", "")


# ─── Stripe 支払い済みリスト取得 ────────────────────────
def get_stripe_paid_customers(hours_back: int = 168) -> list[dict]:
    """
    直近 hours_back 時間以内に支払い完了した Stripe 顧客を返す。
    Returns: [{"email": "...", "amount": 3000, "paid_at": datetime, "payment_id": "..."}, ...]
    """
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
    if not stripe.api_key:
        print("[Reminder] STRIPE_SECRET_KEY が未設定です")
        return []

    since = int((datetime.now(timezone.utc) - timedelta(hours=hours_back)).timestamp())

    customers = []
    try:
        sessions = stripe.checkout.Session.list(
            created={"gte": since},
            status="complete",
            limit=100,
        )
        for session in sessions.auto_paging_iter():
            email = session.get("customer_details", {}).get("email") or session.get("customer_email", "")
            if not email:
                continue
            paid_at = datetime.fromtimestamp(session["created"], tz=timezone.utc)
            customers.append({
                "email":      email.lower().strip(),
                "amount":     session.get("amount_total", 0) // 100,
                "paid_at":    paid_at,
                "payment_id": session["id"],
            })
    except Exception as e:
        print(f"[Reminder] Stripe API エラー: {e}")

    print(f"[Reminder] Stripe 支払い済み: {len(customers)} 件")
    return customers


# ─── フォーム回答済みメール一覧取得 ─────────────────────
def get_form_submitted_emails() -> set[str]:
    """Google フォーム回答スプレッドシートから登録済みメールアドレスを取得"""
    creds = get_credentials()
    client = gspread.authorize(creds)

    spreadsheet_id = os.getenv("SPREADSHEET_ID", "")
    sheet_name     = os.getenv("SHEET_NAME", "フォームの回答 1")

    try:
        spreadsheet = client.open_by_key(spreadsheet_id)
        worksheet   = spreadsheet.worksheet(sheet_name)
        all_records = worksheet.get_all_records()

        emails = set()
        for record in all_records:
            email = record.get(EMAIL_COLUMN, "").strip().lower()
            if email:
                emails.add(email)

        print(f"[Reminder] フォーム回答済み: {len(emails)} 件")
        return emails
    except Exception as e:
        print(f"[Reminder] スプレッドシート読み込みエラー: {e}")
        return set()


# ─── リマインダー送信済みログ ────────────────────────────
REMINDER_LOG_FILE = os.path.join(os.path.dirname(__file__), "reminder_log.json")

def load_reminder_log() -> dict:
    """送信済みリマインダーのログを読み込む"""
    if os.path.exists(REMINDER_LOG_FILE):
        with open(REMINDER_LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_reminder_log(log: dict) -> None:
    """送信済みリマインダーのログを保存する"""
    with open(REMINDER_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2, default=str)


# ─── メール送信 ──────────────────────────────────────────
def _send_email(recipient: str, subject: str, body: str) -> bool:
    """Gmail API でメール送信"""
    try:
        creds   = get_credentials()
        service = build("gmail", "v1", credentials=creds)

        message = MIMEText(body, "plain", "utf-8")
        message["to"]      = recipient
        message["from"]    = GMAIL_SENDER
        message["subject"] = subject

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return True
    except Exception as e:
        print(f"[Reminder] メール送信失敗 → {recipient}: {e}")
        return False


def send_form_link(email: str, amount: int) -> bool:
    """支払い完了後にフォームURLを送信する"""
    if not FORM_URL:
        print("[Reminder] GOOGLE_FORM_URL が未設定です")
        return False

    subject = "【ikedamobile】登録フォームのご案内"
    body = "\n".join([
        "この度はikedamobileにお申し込みいただきありがとうございます。",
        "",
        "お支払いが確認できました。",
        "以下のフォームより、SIM登録に必要な情報をご記入ください。",
        "",
        f"▼ 登録フォーム",
        FORM_URL,
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "⚠️ フォームにご記入いただけないと、SIMの開通手続きができません。",
        "お早めにご記入いただけますようお願いいたします。",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        "ご不明な点がございましたらお気軽にお問い合わせください。",
        "",
        "よろしくお願いいたします。",
        "ikedamobile サポート",
    ])
    return _send_email(email, subject, body)


def send_reminder(email: str, reminder_num: int) -> bool:
    """フォーム記入リマインダーを送信する"""
    if not FORM_URL:
        print("[Reminder] GOOGLE_FORM_URL が未設定です")
        return False

    if reminder_num == 1:
        subject = "【ikedamobile】登録フォームのご記入をお願いします"
        urgency = "まだご記入が完了していないようです。"
    else:
        subject = "【ikedamobile】【重要】登録フォームの未記入のご確認"
        urgency = "登録フォームへのご記入がまだ完了していません。お早めにご記入ください。"

    body = "\n".join([
        "ikedamobileをご利用いただきありがとうございます。",
        "",
        urgency,
        "",
        "SIMカードの開通手続きを進めるため、",
        "以下のフォームへのご記入をお願いいたします。",
        "",
        f"▼ 登録フォーム",
        FORM_URL,
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "⚠️ フォームにご記入いただけないと、SIMの開通手続きができません。",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        "ご不明な点がございましたらお気軽にお問い合わせください。",
        "",
        "よろしくお願いいたします。",
        "ikedamobile サポート",
    ])
    return _send_email(email, subject, body)


# ─── メインチェック ──────────────────────────────────────
def check_and_send_reminders() -> None:
    """
    支払い済みでフォーム未記入の顧客をチェックし、リマインダーを送信する。
    """
    print("[Reminder] チェック開始...")

    paid_customers   = get_stripe_paid_customers()
    submitted_emails = get_form_submitted_emails()
    log              = load_reminder_log()
    now              = datetime.now(timezone.utc)

    sent_form   = 0
    sent_r1     = 0
    sent_r2     = 0
    already_done = 0

    for customer in paid_customers:
        email      = customer["email"]
        paid_at    = customer["paid_at"]
        payment_id = customer["payment_id"]

        # フォーム記入済みならスキップ
        if email in submitted_emails:
            already_done += 1
            continue

        elapsed_hours = (now - paid_at).total_seconds() / 3600
        entry = log.get(payment_id, {})

        # ── フォームURL送信（支払い直後・未送信の場合）
        if not entry.get("form_sent"):
            if send_form_link(email, customer["amount"]):
                entry["form_sent"]    = True
                entry["form_sent_at"] = now.isoformat()
                entry["email"]        = email
                log[payment_id]       = entry
                sent_form += 1
                print(f"[Reminder] フォームURL送信 → {email}")

        # ── 1回目リマインダー
        elif elapsed_hours >= REMINDER_HOURS_1 and not entry.get("reminder1_sent"):
            if send_reminder(email, 1):
                entry["reminder1_sent"]    = True
                entry["reminder1_sent_at"] = now.isoformat()
                log[payment_id]            = entry
                sent_r1 += 1
                print(f"[Reminder] リマインダー1回目 送信 → {email}")

        # ── 2回目リマインダー
        elif elapsed_hours >= REMINDER_HOURS_2 and not entry.get("reminder2_sent"):
            if send_reminder(email, 2):
                entry["reminder2_sent"]    = True
                entry["reminder2_sent_at"] = now.isoformat()
                log[payment_id]            = entry
                sent_r2 += 1
                print(f"[Reminder] リマインダー2回目 送信 → {email}")

    save_reminder_log(log)

    print(f"""
[Reminder] 完了
  フォームURL送信  : {sent_form} 件
  リマインダー1回目: {sent_r1} 件
  リマインダー2回目: {sent_r2} 件
  フォーム記入済み : {already_done} 件（スキップ）
""")


# ─── エントリーポイント ──────────────────────────────────
if __name__ == "__main__":
    check_and_send_reminders()
