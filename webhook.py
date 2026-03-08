"""
Stripe Webhook サーバー

Stripe の支払い完了イベントを受け取り、即座にフォームURLをメール送信する。

■ 起動方法:
  cd jpmob-automation
  source venv/bin/activate
  python webhook.py

■ 必要な環境変数 (.env):
  STRIPE_WEBHOOK_SECRET=whsec_xxxxxxxx  ← Stripe ダッシュボードで取得
  FORM_TRIGGER_SECRET=任意のランダム文字列  ← Google Apps Script と共有
"""

import os
import subprocess
import sys
import stripe
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from datetime import datetime, timezone

from reminder import send_form_link, load_reminder_log, save_reminder_log

load_dotenv()

app = Flask(__name__)


@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload    = request.data
    sig_header = request.headers.get("Stripe-Signature", "")
    secret     = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    # ── 署名検証 ──────────────────────────────────────────
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
    except stripe.errors.SignatureVerificationError:
        print("[Webhook] 署名検証失敗 — 不正なリクエスト")
        return jsonify({"error": "Invalid signature"}), 400
    except Exception as e:
        print(f"[Webhook] リクエスト解析エラー: {e}")
        return jsonify({"error": str(e)}), 400

    # ── checkout.session.completed イベント処理 ───────────
    if event["type"] == "checkout.session.completed":
        session    = event["data"]["object"]
        payment_id = session.get("id", "")
        email      = (
            session.get("customer_details", {}).get("email")
            or session.get("customer_email", "")
            or ""
        ).lower().strip()
        amount = (session.get("amount_total") or 0) // 100

        print(f"[Webhook] 支払い完了: {email} (payment_id={payment_id})")

        if not email:
            print("[Webhook] メールアドレスが取得できませんでした — スキップ")
            return jsonify({"status": "skipped"}), 200

        # ── 重複送信チェック ──────────────────────────────
        log = load_reminder_log()
        if log.get(payment_id, {}).get("form_sent"):
            print(f"[Webhook] フォームURL送信済みのためスキップ: {email}")
            return jsonify({"status": "already_sent"}), 200

        # ── フォームURL送信 ───────────────────────────────
        if send_form_link(email, amount):
            log[payment_id] = {
                "email":        email,
                "form_sent":    True,
                "form_sent_at": datetime.now(timezone.utc).isoformat(),
            }
            save_reminder_log(log)
            print(f"[Webhook] フォームURL送信成功: {email}")
        else:
            print(f"[Webhook] フォームURL送信失敗: {email}")
            return jsonify({"status": "send_failed"}), 500

    return jsonify({"status": "ok"}), 200


# ─────────────────────────────────────────────
# Googleフォーム送信トリガー
# ─────────────────────────────────────────────

MAIN_PID_FILE = os.path.join(os.path.dirname(__file__), "main.pid")


def is_main_running() -> bool:
    """main.py がすでに実行中かどうかを PID ファイルで確認する"""
    if not os.path.exists(MAIN_PID_FILE):
        return False
    try:
        with open(MAIN_PID_FILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)  # プロセスが存在するか確認（シグナルは送らない）
        return True
    except (ValueError, OSError):
        os.remove(MAIN_PID_FILE)
        return False


@app.route("/form-trigger", methods=["POST"])
def form_trigger():
    # ── トークン検証 ──────────────────────────────────────
    secret = os.getenv("FORM_TRIGGER_SECRET", "")
    if secret:
        data = request.get_json(silent=True) or {}
        if data.get("secret") != secret:
            print("[form-trigger] トークン検証失敗 — 不正なリクエスト")
            return jsonify({"error": "Unauthorized"}), 401

    print(f"[form-trigger] フォーム送信を受信: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # ── 二重起動防止 ──────────────────────────────────────
    if is_main_running():
        print("[form-trigger] main.py はすでに実行中のためスキップします")
        return jsonify({"status": "already_running"}), 200

    # ── main.py をバックグラウンドで起動 ─────────────────
    script_dir = os.path.dirname(__file__)
    main_script = os.path.join(script_dir, "main.py")

    proc = subprocess.Popen(
        [sys.executable, main_script],
        cwd=script_dir,
        stdout=open(os.path.join(script_dir, "main.log"), "a"),
        stderr=subprocess.STDOUT,
    )

    with open(MAIN_PID_FILE, "w") as f:
        f.write(str(proc.pid))

    print(f"[form-trigger] main.py を起動しました (PID: {proc.pid})")
    return jsonify({"status": "started", "pid": proc.pid}), 200


if __name__ == "__main__":
    port = int(os.getenv("WEBHOOK_PORT", "5000"))
    print(f"[Webhook] サーバー起動中 — ポート {port}")
    app.run(host="0.0.0.0", port=port)
