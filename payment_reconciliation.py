"""
Stripe 決済とスプレッドシート登録の照合処理。

PaymentIntent を顧客に返す前に申込データを「決済照合キュー」に保存し、
決済成功後はそのキューを唯一の登録元として申し込み管理に反映する。
"""

import json
import os
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import stripe

from application_sheet import (
    append_application_record,
    application_record_exists,
    get_reconciliation_record,
    reconciliation_status_summary,
    set_reconciliation_status,
    upsert_reconciliation_record,
)

PLAN_PRICES = {
    "consul": 3000,
    "online": 3300,
    "general": 3600,
}

SNAPSHOT_FIELDS = (
    "last_kanji",
    "first_kanji",
    "last_kana",
    "first_kana",
    "birthday",
    "sex",
    "document_id",
)


def _now_jst() -> str:
    return datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y/%m/%d %H:%M:%S")


def _payment_time_jst(created_at: int | None) -> str:
    if not created_at:
        return _now_jst()
    return datetime.fromtimestamp(created_at, ZoneInfo("Asia/Tokyo")).strftime(
        "%Y/%m/%d %H:%M:%S"
    )


def _normalize_application(data: dict) -> dict:
    plan = str(data.get("plan", "general"))
    if plan not in PLAN_PRICES:
        raise ValueError("プランを確認してください")

    try:
        lines = int(data.get("lines", 1))
    except (TypeError, ValueError) as error:
        raise ValueError("申込回線数を確認してください") from error

    if not 1 <= lines <= 10:
        raise ValueError("申込回線数を確認してください")

    email = str(data.get("email", "")).strip().lower()
    if not email:
        raise ValueError("メールアドレスを確認してください")

    application_id = str(data.get("application_id", "")).strip() or str(uuid.uuid4())
    if len(application_id) > 120:
        raise ValueError("申込情報を確認してください")

    snapshot = {
        "application_id": application_id,
        "plan": plan,
        "lines": lines,
        "email": email,
        "amount": PLAN_PRICES[plan] * lines,
    }
    for field in SNAPSHOT_FIELDS:
        snapshot[field] = str(data.get(field, "")).strip()

    return snapshot


def _queue_record(
    intent,
    snapshot: dict,
    status: str,
    error_detail: str = "",
) -> dict:
    return {
        "決済ID": intent.id,
        "状態": status,
        "申込ID": snapshot["application_id"],
        "決済日時": _payment_time_jst(getattr(intent, "created", None)),
        "更新日時": _now_jst(),
        "メールアドレス": snapshot["email"],
        "プラン": snapshot["plan"],
        "申込回線数": str(snapshot["lines"]),
        "決済金額": str(snapshot["amount"]),
        "申込データ": json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
        "エラー詳細": error_detail[:500],
    }


def create_payment_intent_with_queue(data: dict):
    """
    PaymentIntent を作成し、クライアントシークレットを返す前に
    申込情報を照合キューへ永続化する。
    """
    snapshot = _normalize_application(data)
    idempotency_key = f"ikedamobile-application-{snapshot['application_id']}"

    intent = stripe.PaymentIntent.create(
        amount=snapshot["amount"],
        currency="jpy",
        receipt_email=snapshot["email"],
        metadata={
            "application_id": snapshot["application_id"],
            "plan": snapshot["plan"],
            "lines": str(snapshot["lines"]),
            "email": snapshot["email"],
        },
        idempotency_key=idempotency_key,
    )
    snapshot["payment_intent_id"] = intent.id

    # この保存に失敗した場合、クライアントシークレットは返さない。
    # 同じ申込IDで再試行すれば Stripe 側は同じ PaymentIntent を返す。
    upsert_reconciliation_record(
        _queue_record(intent, snapshot, "決済待ち")
    )
    print(f"[payment_reconciliation] 決済待ちを記録: payment_id={intent.id}")
    return intent, snapshot


def _load_snapshot(record: dict) -> dict:
    raw = record.get("申込データ", "")
    if not raw:
        raise ValueError("申込データが照合キューにありません")
    snapshot = json.loads(raw)
    required = ("application_id", "plan", "lines", "email", "amount")
    if any(key not in snapshot for key in required):
        raise ValueError("照合キューの申込データが不完全です")
    return snapshot


def _snapshot_matches_intent(snapshot: dict, intent) -> bool:
    metadata = dict(getattr(intent, "metadata", {}) or {})
    return (
        metadata.get("application_id") == str(snapshot["application_id"])
        and metadata.get("plan") == str(snapshot["plan"])
        and metadata.get("lines") == str(snapshot["lines"])
        and metadata.get("email", "").lower() == str(snapshot["email"]).lower()
        and int(getattr(intent, "amount", 0)) == int(snapshot["amount"]) * 100
    )


def _application_record(payment_id: str, snapshot: dict) -> dict:
    return {
        "タイムスタンプ": _now_jst(),
        "姓（漢字）": snapshot.get("last_kanji", ""),
        "名（漢字）": snapshot.get("first_kanji", ""),
        "姓（フリガナ）": snapshot.get("last_kana", ""),
        "名（フリガナ）": snapshot.get("first_kana", ""),
        "生年月日": snapshot.get("birthday", ""),
        "性別": snapshot.get("sex", ""),
        "メールアドレス": snapshot["email"],
        "プラン": snapshot["plan"],
        "申込回線数": str(snapshot["lines"]),
        "決済金額": str(snapshot["amount"]),
        "決済ID": payment_id,
        "本人確認書類": snapshot.get("document_id", ""),
        "予約番号案内": "",
    }


def _safe_set_status(payment_id: str, status: str, detail: str = "") -> None:
    try:
        set_reconciliation_status(payment_id, status, detail)
    except Exception as error:
        print(
            "[payment_reconciliation] 照合キューの状態更新失敗: "
            f"payment_id={payment_id}, error={error}"
        )


def record_succeeded_payment(
    payment_intent_id: str,
    application_data: dict | None = None,
) -> dict:
    """
    Stripe の実データを再取得してから申し込み管理へ反映する。

    成功を返すのは、申し込み管理に決済IDを再読込して確認できた場合だけ。
    """
    intent = stripe.PaymentIntent.retrieve(payment_intent_id)
    if intent.status != "succeeded":
        return {"status": "not_succeeded", "payment_status": intent.status}

    record = get_reconciliation_record(payment_intent_id)

    # 配布前の旧データなどでキューがない場合だけ、クライアントデータを
    # Stripe metadata と照合してキューを復元する。
    if record is None:
        if not application_data:
            print(
                "[payment_reconciliation] キュー未登録の決済を要確認にしました: "
                f"payment_id={payment_intent_id}"
            )
            return {"status": "needs_review"}

        snapshot = _normalize_application(application_data)
        snapshot["payment_intent_id"] = payment_intent_id
        if not _snapshot_matches_intent(snapshot, intent):
            print(
                "[payment_reconciliation] 決済内容と申込内容が一致しません: "
                f"payment_id={payment_intent_id}"
            )
            return {"status": "needs_review"}

        upsert_reconciliation_record(
            _queue_record(intent, snapshot, "決済済み・登録待ち")
        )
        record = get_reconciliation_record(payment_intent_id)

    try:
        snapshot = _load_snapshot(record or {})
    except Exception as error:
        _safe_set_status(payment_intent_id, "要確認", str(error))
        return {"status": "needs_review"}

    if not _snapshot_matches_intent(snapshot, intent):
        _safe_set_status(
            payment_intent_id,
            "要確認",
            "Stripeの決済内容と照合キューの内容が一致しません",
        )
        return {"status": "needs_review"}

    if application_record_exists(payment_intent_id):
        _safe_set_status(payment_intent_id, "登録済み")
        return {"status": "recorded", "already_exists": True}

    _safe_set_status(payment_intent_id, "登録処理中")
    try:
        append_application_record(_application_record(payment_intent_id, snapshot))
        if not application_record_exists(payment_intent_id):
            raise RuntimeError("申し込み管理への登録確認ができませんでした")
    except Exception as error:
        _safe_set_status(payment_intent_id, "決済済み・登録待ち", str(error))
        print(
            "[payment_reconciliation] 申し込み管理への登録保留: "
            f"payment_id={payment_intent_id}, error={error}"
        )
        return {"status": "pending"}

    _safe_set_status(payment_intent_id, "登録済み")
    print(f"[payment_reconciliation] 申し込み管理へ登録完了: payment_id={payment_intent_id}")
    return {"status": "recorded", "already_exists": False}


def reconcile_recent_payments() -> dict:
    """最近の決済済み PaymentIntent を再照合して未登録分を回収する。"""
    lookback_hours = max(
        1,
        int(os.getenv("PAYMENT_RECONCILIATION_LOOKBACK_HOURS", "168")),
    )
    cutoff = int(time.time()) - (lookback_hours * 60 * 60)
    summary = {"checked": 0, "recorded": 0, "pending": 0, "needs_review": 0}

    intents = stripe.PaymentIntent.list(
        limit=100,
        created={"gte": cutoff},
    )

    for intent in intents.auto_paging_iter():
        if intent.status != "succeeded":
            continue
        if not dict(getattr(intent, "metadata", {}) or {}).get("application_id"):
            continue

        summary["checked"] += 1
        try:
            result = record_succeeded_payment(intent.id)
            status = result.get("status", "pending")
            if status in summary:
                summary[status] += 1
        except Exception as error:
            summary["pending"] += 1
            print(
                "[payment_reconciliation] 自動照合で保留: "
                f"payment_id={intent.id}, error={error}"
            )

    return summary


def get_reconciliation_summary() -> dict[str, int]:
    return reconciliation_status_summary()
