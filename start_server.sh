#!/bin/bash
# ============================================================
# ikedamobile Webhook サーバー起動スクリプト
#
# 起動内容:
#   1. webhook.py (Flask) を起動
#   2. Cloudflare Quick Tunnel を起動して公開 URL を取得
#   3. Stripe の Webhook エンドポイント URL を自動更新
#
# 使い方:
#   bash start_server.sh
# ============================================================

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$DIR/venv/bin/python"
CLOUDFLARED="/opt/homebrew/bin/cloudflared"
PORT=5000
WEBHOOK_ENDPOINT_ID="we_1T7J3DBeKLwVbScZPszfOoN8"

cd "$DIR"

# ── 既存プロセスを停止 ─────────────────────────────────────
echo "[起動] 既存プロセスを停止中..."
pkill -f "webhook.py" 2>/dev/null || true
pkill -f "cloudflared tunnel" 2>/dev/null || true
sleep 1

# ── webhook.py を起動 ─────────────────────────────────────
echo "[起動] webhook サーバーを起動中 (port $PORT)..."
PYTHONUNBUFFERED=1 "$PYTHON" "$DIR/webhook.py" >> "$DIR/webhook.log" 2>&1 &
WEBHOOK_PID=$!
sleep 2

# サーバーが起動したか確認
if ! kill -0 "$WEBHOOK_PID" 2>/dev/null; then
    echo "[エラー] webhook.py の起動に失敗しました"
    exit 1
fi
echo "[起動] webhook サーバー起動完了 (PID: $WEBHOOK_PID)"

# ── Cloudflare Quick Tunnel を起動 ────────────────────────
echo "[起動] Cloudflare Tunnel を起動中..."
TUNNEL_LOG=$(mktemp)
"$CLOUDFLARED" tunnel --url "http://localhost:$PORT" --no-autoupdate > "$TUNNEL_LOG" 2>&1 &
TUNNEL_PID=$!

# URL が出るまで最大 30 秒待機
TUNNEL_URL=""
for i in $(seq 1 30); do
    TUNNEL_URL=$(grep -o 'https://[a-zA-Z0-9\-]*\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | head -1)
    if [ -n "$TUNNEL_URL" ]; then
        break
    fi
    sleep 1
done

if [ -z "$TUNNEL_URL" ]; then
    echo "[エラー] Cloudflare Tunnel の URL を取得できませんでした"
    cat "$TUNNEL_LOG"
    exit 1
fi

WEBHOOK_URL="${TUNNEL_URL}/webhook"
FORM_TRIGGER_URL="${TUNNEL_URL}/form-trigger"
echo "[起動] Tunnel URL: $WEBHOOK_URL"

# ── Stripe Webhook エンドポイント URL を更新 ──────────────
echo "[起動] Stripe Webhook URL を更新中..."
"$PYTHON" - <<EOF
import stripe
from dotenv import load_dotenv
import os

load_dotenv("$DIR/.env")
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

endpoint = stripe.WebhookEndpoint.modify(
    "$WEBHOOK_ENDPOINT_ID",
    url="$WEBHOOK_URL",
)
print(f"[起動] Stripe Webhook URL 更新完了: {endpoint.url}")
EOF

echo ""
echo "============================================"
echo "  ikedamobile Webhook サーバー 起動完了"
echo "  Webhook URL      : $WEBHOOK_URL"
echo "  フォームトリガーURL: $FORM_TRIGGER_URL"
echo "  PID (webhook)    : $WEBHOOK_PID"
echo "  PID (tunnel)     : $TUNNEL_PID"
echo "  ログ: $DIR/webhook.log"
echo ""
echo "  ★ Google Apps Script の URL を以下に更新してください:"
echo "     $FORM_TRIGGER_URL"
echo "============================================"
