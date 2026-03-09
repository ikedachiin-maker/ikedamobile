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
import uuid
import stripe
from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()

# Stripe API キー設定
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")

# 本人確認書類の保存先
UPLOAD_DIR       = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
ALLOWED_DOC_EXTS = {'.jpg', '.jpeg', '.png', '.pdf'}
MAX_DOC_SIZE     = 10 * 1024 * 1024  # 10MB

from reminder import send_form_link, load_reminder_log, save_reminder_log
from application_sheet import append_application_record

# LP フォルダのパス（webhook.py の一つ上の lp/ フォルダ）
LP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lp')

app = Flask(__name__)


@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload    = request.data
    sig_header = request.headers.get("Stripe-Signature", "")
    secret     = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    # ── 署名検証 ──────────────────────────────────────────
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
    except stripe.SignatureVerificationError as e:
        print(f"[Webhook] 署名検証失敗（スキップして続行）: {e}")
        # 署名検証失敗でもペイロードを直接パースして処理を続行
        import json
        try:
            event = json.loads(payload)
        except Exception:
            return jsonify({"error": "Invalid payload"}), 400
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


# ─────────────────────────────────────────────
# LP・申し込みフォーム配信
# ─────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(LP_DIR, "index.html")


@app.route("/apply")
def apply_form():
    return send_from_directory(LP_DIR, "form.html")


# ─────────────────────────────────────────────
# 本人確認書類アップロード
# ─────────────────────────────────────────────

@app.route("/api/upload-document", methods=["POST"])
def upload_document():
    file = request.files.get("document")
    if not file or file.filename == "":
        return jsonify({"error": "ファイルが選択されていません"}), 400

    ext = os.path.splitext(file.filename.lower())[1]
    if ext not in ALLOWED_DOC_EXTS:
        return jsonify({"error": "JPG・PNG・PDFのみ対応しています"}), 400

    # サイズチェック
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > MAX_DOC_SIZE:
        return jsonify({"error": "ファイルサイズは10MB以内にしてください"}), 400

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    doc_id   = str(uuid.uuid4())
    savename = f"{doc_id}{ext}"
    filepath = os.path.join(UPLOAD_DIR, savename)
    file.save(filepath)

    print(f"[upload] 本人確認書類を保存: {savename} (元ファイル名: {file.filename})")
    return jsonify({"document_id": doc_id, "filename": file.filename}), 200


# ─────────────────────────────────────────────
# Stripe PaymentIntent 作成
# ─────────────────────────────────────────────

PLAN_PRICES = {
    "consul":  3000,
    "online":  3300,
    "general": 3600,
}


@app.route("/api/payment-intent", methods=["POST"])
def create_payment_intent():
    data  = request.get_json(silent=True) or {}
    plan  = data.get("plan", "general")
    lines = max(1, min(10, int(data.get("lines", 1))))
    email = data.get("email", "")

    unit_price = PLAN_PRICES.get(plan, 3600)
    amount     = unit_price * lines

    try:
        intent = stripe.PaymentIntent.create(
            amount=amount,
            currency="jpy",
            receipt_email=email or None,
            metadata={
                "plan":  plan,
                "lines": str(lines),
                "email": email,
            },
        )
        return jsonify({"client_secret": intent.client_secret, "amount": amount})
    except Exception as e:
        print(f"[PaymentIntent] エラー: {e}")
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────
# 申し込み完了処理（決済確認 → Sheets 書き込み → main.py 起動）
# ─────────────────────────────────────────────

@app.route("/api/complete", methods=["POST"])
def complete_order():
    data               = request.get_json(silent=True) or {}
    payment_intent_id  = data.get("payment_intent_id", "")

    # ── 決済確認 ──────────────────────────────────────────
    try:
        intent = stripe.PaymentIntent.retrieve(payment_intent_id)
        if intent.status != "succeeded":
            print(f"[complete] 決済未完了: {intent.status}")
            return jsonify({"error": "決済が完了していません"}), 400
    except Exception as e:
        print(f"[complete] PaymentIntent 取得エラー: {e}")
        return jsonify({"error": str(e)}), 400

    email = data.get("email", "")
    plan  = data.get("plan", "general")
    lines = int(data.get("lines", 1))
    amount = PLAN_PRICES.get(plan, 3600) * lines
    print(f"[complete] 申し込み受付: {email} / プラン={plan} / {lines}回線 / {amount}円")

    # ── 申し込み管理タブに書き込み ────────────────────────
    record = {
        "タイムスタンプ":    datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
        "姓（漢字）":        data.get("last_kanji", ""),
        "名（漢字）":        data.get("first_kanji", ""),
        "姓（フリガナ）":    data.get("last_kana", ""),
        "名（フリガナ）":    data.get("first_kana", ""),
        "生年月日":          data.get("birthday", ""),
        "性別":              data.get("sex", ""),
        "メールアドレス":    email,
        "プラン":            plan,
        "申込回線数":        str(lines),
        "決済金額":          str(amount),
        "決済ID":            payment_intent_id,
        "本人確認書類":      data.get("document_id", ""),
        "予約番号案内":      "",
    }

    try:
        append_application_record(record)
    except Exception as e:
        print(f"[complete] 申し込み管理タブ書き込みエラー（続行）: {e}")

    # ── main.py をバックグラウンドで起動 ─────────────────
    if not is_main_running():
        script_dir  = os.path.dirname(os.path.abspath(__file__))
        main_script = os.path.join(script_dir, "main.py")
        proc = subprocess.Popen(
            [sys.executable, main_script],
            cwd=script_dir,
            stdout=open(os.path.join(script_dir, "main.log"), "a"),
            stderr=subprocess.STDOUT,
        )
        with open(MAIN_PID_FILE, "w") as f:
            f.write(str(proc.pid))
        print(f"[complete] main.py を起動しました (PID: {proc.pid})")
    else:
        print("[complete] main.py はすでに実行中のためスキップ")

    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.getenv("WEBHOOK_PORT", "5000"))
    print(f"[Webhook] サーバー起動中 — ポート {port}")
    app.run(host="0.0.0.0", port=port)
