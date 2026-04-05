"""
常駐監視スクリプト — 新規申し込みを検知して自動処理

■ 動作:
  1. 5分ごとにスプレッドシートをチェック
  2. 未処理の申し込みがあれば main.py をサブプロセスで起動
  3. main.py 実行中は重複起動しない（ロック機構あり）
  4. 8:00〜20:00 の間のみ動作（jpmob の時間制限に準拠）
  5. 予約番号未発行のSIMがあれば30分おきに再チェック・メール再送

■ 起動方法:
  cd jpmob-automation
  source venv/bin/activate
  python watcher.py

■ 環境変数:
  WATCHER_INTERVAL_SECONDS       チェック間隔（デフォルト: 300 = 5分）
  RETRY_CHECK_INTERVAL_SECONDS   予約番号再チェック間隔（デフォルト: 1800 = 30分）
"""

import os
import sys
import json
import time
import subprocess
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ─── 設定 ─────────────────────────────────────────────
INTERVAL = int(os.getenv("WATCHER_INTERVAL_SECONDS", "300"))  # 5分
RETRY_CHECK_INTERVAL = int(os.getenv("RETRY_CHECK_INTERVAL_SECONDS", "1800"))  # 30分
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable  # 現在の仮想環境の Python
MAIN_SCRIPT = os.path.join(SCRIPT_DIR, "main.py")
RETRY_SCRIPT = os.path.join(SCRIPT_DIR, "retry_send.py")
REASSIGN_SCRIPT = os.path.join(SCRIPT_DIR, "reassign.py")
REASSIGN_CONFIG = os.path.join(SCRIPT_DIR, "reassign_config.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "watcher.log")

# main.py / retry_send.py / reassign.py の実行プロセスを追跡
_running_process: subprocess.Popen | None = None
_retry_process: subprocess.Popen | None = None
_reassign_process: subprocess.Popen | None = None
_last_retry_check: float = 0  # 最後にリトライチェックした時刻


def log(msg: str) -> None:
    """タイムスタンプ付きでログ出力"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)


def is_operational_hours() -> bool:
    """8:00〜20:00 の間か判定"""
    return 8 <= datetime.now().hour < 20


def is_main_running() -> bool:
    """main.py がまだ実行中かチェック"""
    global _running_process
    if _running_process is None:
        return False
    retcode = _running_process.poll()
    if retcode is None:
        return True  # まだ実行中
    # 終了済み
    if retcode == 0:
        log(f"[完了] main.py が正常終了しました (exit code: {retcode})")
    else:
        log(f"[警告] main.py が異常終了しました (exit code: {retcode})")
    _running_process = None
    return False


def has_unprocessed_records() -> bool:
    """
    スプレッドシートに未処理レコードがあるか軽量チェック。
    Selenium を起動せずに API のみで確認する。
    """
    try:
        from sheets_reader import read_spreadsheet_data
        from application_sheet import read_unprocessed_applications

        gform = read_spreadsheet_data()
        app = read_unprocessed_applications()
        total = len(gform) + len(app)

        if total > 0:
            log(f"[検知] 未処理レコード {total} 件（Googleフォーム: {len(gform)} / 専用フォーム: {len(app)}）")
        return total > 0

    except Exception as e:
        log(f"[エラー] スプレッドシート確認失敗: {e}")
        return False


def start_main() -> None:
    """main.py をサブプロセスで起動"""
    global _running_process

    log("[起動] main.py を開始します...")

    main_log = open(os.path.join(SCRIPT_DIR, "main.log"), "a")
    _running_process = subprocess.Popen(
        [PYTHON, MAIN_SCRIPT],
        cwd=SCRIPT_DIR,
        stdout=main_log,
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    log(f"[起動] main.py を起動しました (PID: {_running_process.pid})")


def has_pending_reservations() -> bool:
    """予約番号未発行のSIMがあるかチェック"""
    try:
        from assignment_sheet import get_or_create_assignment_sheet, HEADERS

        worksheet = get_or_create_assignment_sheet()
        all_rows = worksheet.get_all_values()
        if len(all_rows) <= 1:
            return False

        yoyaku_idx = HEADERS.index("予約番号")
        card_id_idx = HEADERS.index("カードID")

        pending = 0
        for row in all_rows[1:]:
            if len(row) > card_id_idx and row[card_id_idx].strip():
                if len(row) <= yoyaku_idx or not row[yoyaku_idx].strip():
                    pending += 1

        if pending > 0:
            log(f"[検知] 予約番号未発行 {pending} 件")
        return pending > 0

    except Exception as e:
        log(f"[エラー] 予約番号チェック失敗: {e}")
        return False


def is_retry_running() -> bool:
    """retry_send.py がまだ実行中かチェック"""
    global _retry_process
    if _retry_process is None:
        return False
    retcode = _retry_process.poll()
    if retcode is None:
        return True
    if retcode == 0:
        log(f"[完了] retry_send.py が正常終了しました")
    else:
        log(f"[警告] retry_send.py が異常終了しました (exit code: {retcode})")
    _retry_process = None
    return False


def start_retry() -> None:
    """retry_send.py をサブプロセスで起動"""
    global _retry_process, _last_retry_check

    log("[起動] retry_send.py を開始します...")

    retry_log = open(os.path.join(SCRIPT_DIR, "retry_send.log"), "a")
    _retry_process = subprocess.Popen(
        [PYTHON, RETRY_SCRIPT],
        cwd=SCRIPT_DIR,
        stdout=retry_log,
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    _last_retry_check = time.time()
    log(f"[起動] retry_send.py を起動しました (PID: {_retry_process.pid})")


def has_pending_reassignments() -> bool:
    """reassign_config.json に pending タスクがあるかチェック"""
    try:
        with open(REASSIGN_CONFIG, "r") as f:
            config = json.load(f)
        pending = [t for t in config.get("tasks", []) if t.get("status") == "pending"]
        if pending:
            log(f"[検知] SIM再割り当てタスク {len(pending)} 件が pending です")
        return len(pending) > 0
    except (FileNotFoundError, json.JSONDecodeError):
        return False


def is_reassign_running() -> bool:
    """reassign.py がまだ実行中かチェック"""
    global _reassign_process
    if _reassign_process is None:
        return False
    retcode = _reassign_process.poll()
    if retcode is None:
        return True
    if retcode == 0:
        log(f"[完了] reassign.py が正常終了しました")
    else:
        log(f"[警告] reassign.py が異常終了しました (exit code: {retcode})")
    _reassign_process = None
    return False


def start_reassign() -> None:
    """reassign.py をサブプロセスで起動"""
    global _reassign_process

    log("[起動] reassign.py を開始します...")

    reassign_log = open(os.path.join(SCRIPT_DIR, "reassign.log"), "a")
    _reassign_process = subprocess.Popen(
        [PYTHON, REASSIGN_SCRIPT],
        cwd=SCRIPT_DIR,
        stdout=reassign_log,
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    log(f"[起動] reassign.py を起動しました (PID: {_reassign_process.pid})")


def run_watcher() -> None:
    """メインループ"""
    global _last_retry_check
    _last_retry_check = 0.0  # Python 3.12+ の UnboundLocalError 対策
    log("=" * 55)
    log("  ikedamobile 常駐監視 開始")
    log(f"  チェック間隔: {INTERVAL}秒（{INTERVAL // 60}分）")
    log(f"  稼働時間帯: 8:00〜20:00")
    log(f"  Python: {PYTHON}")
    log("=" * 55)

    while True:
        try:
            now = datetime.now()

            # 時間外はスキップ
            if not is_operational_hours():
                # 1時間ごとにログ出力（ログが静かすぎないように）
                if now.minute < (INTERVAL // 60):
                    log(f"[待機] 時間外（{now.strftime('%H:%M')}）— 8:00〜20:00 に稼働します")
                time.sleep(INTERVAL)
                continue

            # main.py / retry_send.py / reassign.py が実行中ならスキップ
            if is_main_running():
                log("[スキップ] main.py 実行中のため次回チェックまで待機")
                time.sleep(INTERVAL)
                continue

            if is_retry_running():
                log("[スキップ] retry_send.py 実行中のため次回チェックまで待機")
                time.sleep(INTERVAL)
                continue

            if is_reassign_running():
                log("[スキップ] reassign.py 実行中のため次回チェックまで待機")
                time.sleep(INTERVAL)
                continue

            # スプレッドシートをチェック（新規申し込み）
            log(f"[チェック] スプレッドシートを確認中... ({now.strftime('%H:%M')})")
            if has_unprocessed_records():
                start_main()
            else:
                log("[結果] 未処理レコードなし")

                # 新規がなければ、予約番号未発行の再チェック
                elapsed = time.time() - _last_retry_check
                if elapsed >= RETRY_CHECK_INTERVAL:
                    if has_pending_reservations():
                        start_retry()
                    else:
                        _last_retry_check = time.time()

                # SIM再割り当てタスクのチェック
                if not is_retry_running() and has_pending_reassignments():
                    start_reassign()

        except KeyboardInterrupt:
            log("[停止] Ctrl+C — 監視を終了します")
            if _running_process and _running_process.poll() is None:
                log("[停止] 実行中の main.py を終了しています...")
                _running_process.terminate()
                _running_process.wait(timeout=30)
            if _retry_process and _retry_process.poll() is None:
                log("[停止] 実行中の retry_send.py を終了しています...")
                _retry_process.terminate()
                _retry_process.wait(timeout=30)
            if _reassign_process and _reassign_process.poll() is None:
                log("[停止] 実行中の reassign.py を終了しています...")
                _reassign_process.terminate()
                _reassign_process.wait(timeout=30)
            break

        except Exception as e:
            log(f"[エラー] 予期しないエラー: {e}")
            import traceback
            traceback.print_exc()

        time.sleep(INTERVAL)


if __name__ == "__main__":
    run_watcher()
