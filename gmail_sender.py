"""Gmail API で各クライアントに予約番号・有効期限をメール送信するモジュール"""
import os
import base64
from email.mime.text import MIMEText
from googleapiclient.discovery import build
from sheets_reader import get_credentials
from dotenv import load_dotenv

load_dotenv()


def build_body(record: dict, sim_phone: str, yoyaku_number: str, expiry_date: str) -> str:
    """1件分のメール本文を組み立てる"""
    name = record.get("名前", "")
    lines = [
        f"{name} 様",
        "",
        "このたびはお申し込みいただきありがとうございます。",
        "以下の内容でご登録が完了しましたのでお知らせいたします。",
        "",
        "【SIM情報】",
        f"  電話番号　：{sim_phone}",
        f"  予約番号　：{yoyaku_number}",
        f"  有効期限　：{expiry_date}",
        "",
        "ご不明な点がございましたらお気軽にお問い合わせください。",
        "",
        "よろしくお願いいたします。",
    ]
    return "\n".join(lines)


def send_gmail(assignments: list[dict]) -> None:
    """
    各クライアントのメールアドレスに予約番号・有効期限を個別送信する。

    assignments: [{"record": {...}, "sim_phone": "...", "yoyaku_number": "...", "expiry_date": "..."}, ...]
    """
    creds   = get_credentials()
    service = build("gmail", "v1", credentials=creds)

    sender  = os.getenv("GMAIL_SENDER")
    subject = os.getenv("GMAIL_SUBJECT", "【ikedamobile】SIM情報のご連絡")
    email_column = os.getenv("GMAIL_EMAIL_COLUMN", "メールアドレス")

    success_count = 0
    error_count   = 0

    # 顧客ごとに集約（同一顧客に複数SIMがある場合はまとめて1通）
    customer_map: dict[str, dict] = {}
    for a in assignments:
        key = a["record"].get(email_column, "").strip()
        if not key:
            continue
        if key not in customer_map:
            customer_map[key] = {
                "record": a["record"],
                "sims":   [],
            }
        customer_map[key]["sims"].append({
            "sim_phone":     a.get("sim_phone", ""),
            "yoyaku_number": a.get("yoyaku_number", ""),
            "expiry_date":   a.get("expiry_date", ""),
        })

    for i, (recipient, data) in enumerate(customer_map.items(), 1):
        record = data["record"]
        name   = f"{record.get('姓（漢字）', '')} {record.get('名（漢字）', '')}".strip()
        sims   = data["sims"]

        # 複数SIMの場合はまとめてメール本文を構築
        if len(sims) == 1:
            body = build_body(record, sims[0]["sim_phone"], sims[0]["yoyaku_number"], sims[0]["expiry_date"])
        else:
            sim_lines = []
            for j, sim in enumerate(sims, 1):
                sim_lines += [
                    f"【SIM情報 {j}】",
                    f"  電話番号　：{sim['sim_phone']}",
                    f"  予約番号　：{sim['yoyaku_number']}",
                    f"  有効期限　：{sim['expiry_date']}",
                    "",
                ]
            body = "\n".join([
                f"{name} 様",
                "",
                "このたびはお申し込みいただきありがとうございます。",
                "以下の内容でご登録が完了しましたのでお知らせいたします。",
                "",
                *sim_lines,
                "ご不明な点がございましたらお気軽にお問い合わせください。",
                "",
                "よろしくお願いいたします。",
            ])

        message = MIMEText(body, "plain", "utf-8")
        message["to"]      = recipient
        message["from"]    = sender
        message["subject"] = subject

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        try:
            service.users().messages().send(userId="me", body={"raw": raw}).execute()
            print(f"[Gmail] ({i}/{len(customer_map)}) 送信成功 → {recipient}（{name}）")
            success_count += 1
        except Exception as e:
            print(f"[Gmail] ({i}/{len(customer_map)}) 送信失敗 → {recipient}: {e}")
            error_count += 1

    print(f"[Gmail] 完了 — 成功: {success_count} 件 / 失敗: {error_count} 件")
