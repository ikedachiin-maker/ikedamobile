"""jpmob 管理コンソールへの自動入力モジュール（Selenium）"""
import os
import re
import json
import time
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv

load_dotenv()

LIST_URL   = "https://console.jpmob.jp/sonet_cards/iot_external_index"
LOGIN_URL  = "https://console.jpmob.jp/admin_users/sign_in"

# これらの状態のカードは処理をスキップする（すでに処理済み or 解約済み）
SKIP_STATUSES = {"MNP転出中", "解約", "解約済み"}

# ── 開通日フィルター ─────────────────────────────────────────────
# この日以降に開通したカードのみ処理対象とする（.env で変更可能）
_cutoff_str = os.getenv("JPMOB_OPEN_DATE_CUTOFF", "2026-03-11")
try:
    OPEN_DATE_CUTOFF = datetime.strptime(_cutoff_str, "%Y-%m-%d")
except ValueError:
    OPEN_DATE_CUTOFF = datetime(2026, 3, 11)
print(f"[jpmob] 開通日フィルター: {OPEN_DATE_CUTOFF.strftime('%Y年%m月%d日')} 以降のカードのみ処理")


# ─────────────────────────────────────────────
# スキップ済みカードID キャッシュ
#   開通日が OPEN_DATE_CUTOFF より前のカードIDを記録し、
#   次回以降 Selenium での詳細ページ読み込みを省略する。
# ─────────────────────────────────────────────

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SKIP_CACHE_FILE = os.path.join(_SCRIPT_DIR, "skipped_cards.json")
_skip_cache: set[str] = set()


def _load_skip_cache() -> set[str]:
    """スキップ済みカードIDキャッシュを読み込む"""
    global _skip_cache
    try:
        with open(_SKIP_CACHE_FILE, "r") as f:
            data = json.load(f)
            _skip_cache = set(data.get("skipped_card_ids", []))
    except (FileNotFoundError, json.JSONDecodeError):
        _skip_cache = set()
    print(f"[jpmob] スキップキャッシュ読み込み: {len(_skip_cache)} 件")
    return _skip_cache


def _save_skip_cache() -> None:
    """スキップ済みカードIDキャッシュを保存する"""
    with open(_SKIP_CACHE_FILE, "w") as f:
        json.dump(
            {"skipped_card_ids": sorted(_skip_cache),
             "cutoff": OPEN_DATE_CUTOFF.strftime("%Y-%m-%d"),
             "updated_at": datetime.now().isoformat()},
            f, indent=2,
        )
    print(f"[jpmob] スキップキャッシュを保存: {len(_skip_cache)} 件")


def _add_to_skip_cache(card_id: str) -> None:
    """カードIDをスキップキャッシュに追加（メモリ上のみ、後でまとめて保存）"""
    _skip_cache.add(card_id)


# ─────────────────────────────────────────────
# 入力済みカードID 追跡
#   enter_user_info 成功直後にファイルへ記録し、
#   スプレッドシート書き込み失敗時でも次回の再試行を防止する。
# ─────────────────────────────────────────────

_ENTERED_CARDS_FILE = os.path.join(_SCRIPT_DIR, "entered_cards.json")
_entered_cards: set[str] = set()


def _load_entered_cards() -> set[str]:
    """入力済みカードIDを読み込む"""
    global _entered_cards
    try:
        with open(_ENTERED_CARDS_FILE, "r") as f:
            data = json.load(f)
            _entered_cards = set(data.get("entered_card_ids", []))
    except (FileNotFoundError, json.JSONDecodeError):
        _entered_cards = set()
    print(f"[jpmob] 入力済みカード読み込み: {len(_entered_cards)} 件")
    return _entered_cards


def _add_to_entered_cards(card_id: str) -> None:
    """カードIDを入力済みとして即ファイルに保存する（データ消失防止）"""
    _entered_cards.add(card_id)
    try:
        with open(_ENTERED_CARDS_FILE, "w") as f:
            json.dump(
                {"entered_card_ids": sorted(_entered_cards),
                 "updated_at": datetime.now().isoformat()},
                f, indent=2,
            )
    except Exception as e:
        print(f"[jpmob] 入力済みカード保存エラー: {e}")


# ─────────────────────────────────────────────
# ドライバ・ログイン
# ─────────────────────────────────────────────

def create_driver(headless: bool = False) -> webdriver.Chrome:
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,900")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.implicitly_wait(10)
    return driver


def login(driver, wait, username: str, password: str) -> None:
    print(f"[jpmob] ログイン中...")
    driver.get(LOGIN_URL)
    wait.until(EC.presence_of_element_located((By.ID, "admin_user_email"))).send_keys(username)
    driver.find_element(By.ID, "admin_user_password").send_keys(password)
    driver.find_element(By.CSS_SELECTOR, "input[type='submit']").click()
    wait.until(EC.url_changes(LOGIN_URL))
    print("[jpmob] ログイン完了")
    time.sleep(1)


# ─────────────────────────────────────────────
# 開通済みカード一覧取得
# ─────────────────────────────────────────────

def get_open_cards(driver, wait) -> list[dict]:
    """状態が「開通済み」のカード一覧を取得して返す"""
    driver.get(LIST_URL)
    time.sleep(2)

    # 状態フィルターを「開通済み」に変更
    status_select = wait.until(EC.presence_of_element_located(
        (By.XPATH, "//select[.//option[normalize-space(text())='開通済み']]")
    ))
    Select(status_select).select_by_visible_text("開通済み")
    time.sleep(2)

    # 件数を全件表示に変更
    try:
        per_page = driver.find_element(By.XPATH, "//select[.//option[@value='9999999']]")
        Select(per_page).select_by_value("9999999")
        time.sleep(2)
    except Exception:
        pass

    # 電話番号リンクからカードIDと電話番号を収集
    links = driver.find_elements(By.CSS_SELECTOR, "table tbody tr td a")
    open_cards = []
    for link in links:
        href = link.get_attribute("href") or ""
        text = link.text.strip()
        m = re.search(r"/sonet_cards/(\d+)", href)
        if m and text:
            open_cards.append({"phone": text, "card_id": m.group(1)})

    print(f"[jpmob] 開通済みカード: {len(open_cards)} 件")
    return open_cards


# ─────────────────────────────────────────────
# 名前・生年月日のユーティリティ
# ─────────────────────────────────────────────

def split_name(full_name: str) -> tuple[str, str]:
    """フルネームを姓・名に分割（スペース区切り）"""
    full_name = (full_name or "").strip()
    parts = re.split(r"[\s\u3000]+", full_name)
    if len(parts) >= 2:
        return parts[0], "".join(parts[1:])
    return full_name, ""


def normalize_birthday(birthday_str) -> str:
    """生年月日を YYYY-MM-DD 形式に正規化する"""
    # 整数（例: 19670518）は文字列に変換
    if isinstance(birthday_str, int):
        birthday_str = str(birthday_str)
    s = (str(birthday_str) if birthday_str else "").strip()
    # ドット区切り（例: 1963.11.19）を対応
    if re.match(r"^\d{4}\.\d{1,2}\.\d{1,2}$", s):
        parts = s.split(".")
        return f"{parts[0]}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    if re.match(r"^\d{4}/\d{2}/\d{2}$", s):
        return s.replace("/", "-")
    m = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    for fmt in ["%Y%m%d", "%d/%m/%Y"]:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return s


# ─────────────────────────────────────────────
# ユーザー情報入力（カタカナ更新フォーム）
# ─────────────────────────────────────────────

def get_sex_value(record: dict) -> str:
    """
    スプレッドシートの性別をjpmobの値（male/female）に変換する。
    性別が不明・未入力の場合は空文字を返す（必須項目チェックで弾かせる）。
    """
    sex_raw = record.get("性別", "").strip().lower()
    if sex_raw in ("女性", "female", "f"):
        return "female"
    if sex_raw in ("男性", "male", "m"):
        return "male"
    # 未入力・不明の場合は空文字を返す
    # → 必須項目チェックでスキップされ、誤った性別で登録されるのを防ぐ
    if sex_raw:
        print(f"[jpmob] ⚠️ 性別の値を認識できません: '{record.get('性別', '')}' → スキップ対象")
    return ""


def get_label_value(driver, label_text: str) -> str:
    """
    jpmob カード詳細ページのフィールド値を取得する。
    HTML 構造: <label><strong>ラベル</strong></label> の次の <div><p>値</p></div>
    """
    try:
        xpath = (
            f"//label[.//strong[normalize-space()='{label_text}']]"
            f"/following-sibling::div[1]//p[1]"
        )
        return driver.find_element(By.XPATH, xpath).text.strip()
    except Exception:
        return ""


def parse_open_date(date_str: str) -> datetime | None:
    """
    '2026年03月13日' 形式の文字列を datetime に変換する。
    パースできない場合は None を返す。
    """
    m = re.match(r"(\d{4})年(\d{2})月(\d{2})日", date_str.strip())
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def get_card_status(driver) -> str:
    """
    現在開いているカード詳細ページの「状態」を取得する。
    dl/dt/dd 構造と table/th/td 構造の両方を試みる。
    """
    for xpath in [
        "//dt[normalize-space()='状態']/following-sibling::dd[1]",
        "//th[normalize-space()='状態']/following-sibling::td[1]",
        "//td[normalize-space()='状態']/following-sibling::td[1]",
    ]:
        try:
            el = driver.find_element(By.XPATH, xpath)
            return el.text.strip()
        except Exception:
            continue
    return ""


def _verify_submission(driver, card_id: str) -> bool:
    """
    フォーム送信後にモーダルが閉じたか、エラーメッセージがないかを検証する。
    成功 → True, 失敗/不明 → False
    """
    try:
        modal = driver.find_element(By.ID, "update_mnp_user_info")
        if modal.is_displayed():
            # モーダルがまだ表示されている → エラーの可能性
            # エラーメッセージを検索（Bootstrap の一般的なパターン）
            error_selectors = [
                "#update_mnp_user_info .alert-danger",
                "#update_mnp_user_info .alert-warning",
                "#update_mnp_user_info .error",
                "#update_mnp_user_info .help-block",
                "#update_mnp_user_info .invalid-feedback",
                "#update_mnp_user_info .field_with_errors",
            ]
            error_texts = []
            for sel in error_selectors:
                try:
                    errors = driver.find_elements(By.CSS_SELECTOR, sel)
                    for e in errors:
                        txt = e.text.strip()
                        if txt:
                            error_texts.append(txt)
                except Exception:
                    pass

            if error_texts:
                print(
                    f"[jpmob] ❌ フォームエラー検出: card_id={card_id} "
                    f"— {'; '.join(error_texts)}"
                )
            else:
                # エラーメッセージなしだがモーダルが開いたまま
                # ページ全体のアラートも確認
                try:
                    page_alerts = driver.find_elements(By.CSS_SELECTOR, ".alert")
                    for a in page_alerts:
                        txt = a.text.strip()
                        if txt:
                            error_texts.append(f"ページアラート: {txt}")
                except Exception:
                    pass

                if error_texts:
                    print(
                        f"[jpmob] ❌ ページエラー検出: card_id={card_id} "
                        f"— {'; '.join(error_texts)}"
                    )
                else:
                    print(
                        f"[jpmob] ⚠️ モーダルが閉じていません（原因不明）: "
                        f"card_id={card_id}"
                    )

            # デバッグ用スクリーンショットを保存
            _save_debug_screenshot(driver, card_id, "submit_error")
            return False

        # モーダルが閉じている → 送信成功の可能性が高い
        return True

    except Exception:
        # モーダル要素が見つからない → 正常に閉じた（DOMから削除された）
        return True


def _save_debug_screenshot(driver, card_id: str, suffix: str) -> None:
    """デバッグ用のスクリーンショットを保存する"""
    try:
        screenshot_dir = os.path.join(_SCRIPT_DIR, "debug_screenshots")
        os.makedirs(screenshot_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(screenshot_dir, f"{card_id}_{suffix}_{timestamp}.png")
        driver.save_screenshot(path)
        print(f"[jpmob]   スクリーンショット保存: {path}")
    except Exception as e:
        print(f"[jpmob]   スクリーンショット保存エラー: {e}")


def enter_user_info(driver, wait, card_id: str, record: dict) -> bool:
    """
    1枚のSIMカードにスプレッドシートの顧客情報を入力する。
    状態が「MNP転出中」「解約」等の場合はスキップして False を返す。
    正常に入力した場合は True を返す。
    Selenium の例外が発生しても False を返し、処理全体は止めない。
    """
    try:
        return _enter_user_info_impl(driver, wait, card_id, record)
    except Exception as e:
        print(f"[jpmob] スキップ（操作エラー）: card_id={card_id} — {type(e).__name__}: {e}")
        return False


def _enter_user_info_impl(driver, wait, card_id: str, record: dict) -> bool:
    """enter_user_info の実処理"""
    url = f"https://console.jpmob.jp/sonet_cards/{card_id}?locale=ja"
    driver.get(url)
    time.sleep(1)

    # ── 状態チェック（MNP転出中・解約はスキップ）──────────
    status = get_card_status(driver)
    if status in SKIP_STATUSES:
        print(f"[jpmob] スキップ（状態={status}）: card_id={card_id}")
        return False
    if status and status != "開通済み":
        print(f"[jpmob] 想定外の状態「{status}」のためスキップ: card_id={card_id}")
        return False

    # ── 開通日チェック（OPEN_DATE_CUTOFF 以降のカードのみ処理）──
    open_date_str = get_label_value(driver, "開通日")
    open_date     = parse_open_date(open_date_str)
    if open_date is None:
        print(f"[jpmob] スキップ（開通日が取得できません）: card_id={card_id}")
        return False
    if open_date < OPEN_DATE_CUTOFF:
        _add_to_skip_cache(card_id)
        print(
            f"[jpmob] スキップ（開通日={open_date_str} "
            f"< {OPEN_DATE_CUTOFF.strftime('%Y年%m月%d日')}）: card_id={card_id}"
        )
        return False

    # プランタブをクリック
    wait.until(EC.element_to_be_clickable(
        (By.XPATH, "//a[@href='#sonet_plan' or contains(@href,'#sonet_plan')]")
    )).click()
    time.sleep(1)

    # カタカナ更新ボタン（モーダルトリガー）をクリック
    # ── 既に情報入力済みのカードではボタンが表示されないため、短いタイムアウト（3秒）で判定 ──
    short_wait = WebDriverWait(driver, 3)
    try:
        katakana_btn = short_wait.until(EC.element_to_be_clickable(
            (By.CSS_SELECTOR, "a[data-target='#update_mnp_user_info']")
        ))
    except Exception:
        print(f"[jpmob] スキップ（情報入力済み）: card_id={card_id}")
        _add_to_entered_cards(card_id)
        return False
    driver.execute_script("arguments[0].scrollIntoView(true);", katakana_btn)
    time.sleep(0.5)
    katakana_btn.click()

    # モーダルが開くまで待機
    # ── ボタンクリック後にモーダルが開かない場合、手動操作との競合を疑う ──
    try:
        wait.until(EC.visibility_of_element_located((By.ID, "last_name_kana")))
    except Exception:
        # ボタンが消えていれば手動処理で先に送信されたと判断
        try:
            driver.find_element(By.CSS_SELECTOR, "a[data-target='#update_mnp_user_info']")
            # ボタンがまだある → 手動処理との競合ではなく別の原因
            print(f"[jpmob] スキップ（モーダルが開きませんでした）: card_id={card_id}")
        except Exception:
            # ボタンが消えた → 手動処理で先に入力済み
            print(f"[jpmob] スキップ（手動処理済みを検出）: card_id={card_id}")
            _add_to_entered_cards(card_id)
        return False

    # フォームの各列から直接取得（姓・名は別々の列）
    last_kana   = record.get("姓（フリガナ）", "").strip()
    first_kana  = record.get("名（フリガナ）", "").strip()
    last_kanji  = record.get("姓（漢字）", "").strip()
    first_kanji = record.get("名（漢字）", "").strip()
    birthday    = normalize_birthday(record.get("生年月日", ""))
    sex         = get_sex_value(record)

    # ── 全6項目の必須チェック（1つでも欠けていたら登録しない）──
    required_fields = {
        "姓（フリガナ）": last_kana,
        "名（フリガナ）": first_kana,
        "姓（漢字）":     last_kanji,
        "名（漢字）":     first_kanji,
        "生年月日":       birthday,
        "性別":           sex,
    }
    missing = [name for name, val in required_fields.items() if not val]
    if missing:
        print(
            f"[jpmob] スキップ（必須項目が不足）: card_id={card_id} "
            f"— 不足: {', '.join(missing)}"
        )
        return False

    # ── デバッグ: 入力データをログ出力 ──
    print(
        f"[jpmob]   データ: 姓カナ={last_kana}, 名カナ={first_kana}, "
        f"姓漢字={last_kanji}, 名漢字={first_kanji}, "
        f"誕生日={birthday}, 性別={sex}"
    )

    def fill(field_id, value):
        el = driver.find_element(By.ID, field_id)
        el.clear()
        el.send_keys(value)

    fill("last_name_kana",  last_kana)
    fill("first_name_kana", first_kana)
    fill("last_name",       last_kanji)
    fill("first_name",      first_kanji)
    fill("birthday",        birthday)
    Select(driver.find_element(By.ID, "sex")).select_by_value(sex)

    # ── デバッグ: 入力値の確認（実際にフィールドに入った値）──
    actual_values = {}
    for fid in ["last_name_kana", "first_name_kana", "last_name", "first_name", "birthday"]:
        try:
            actual_values[fid] = driver.find_element(By.ID, fid).get_attribute("value")
        except Exception:
            actual_values[fid] = "取得失敗"
    print(f"[jpmob]   実際の入力値: {actual_values}")

    # 更新ボタンをクリック
    driver.find_element(By.CSS_SELECTOR,
        "#update_mnp_user_info input[type='submit']"
    ).click()
    time.sleep(3)  # 送信処理のため少し長く待つ

    # ── 送信結果を検証 ──────────────────────────
    submit_ok = _verify_submission(driver, card_id)

    # 入力済みとして即ファイルに記録（Step3失敗時の再試行防止）
    _add_to_entered_cards(card_id)

    if submit_ok:
        print(f"[jpmob] ✅ 入力完了（検証OK）: card_id={card_id}")
    else:
        print(f"[jpmob] ⚠️ 入力完了（検証失敗 — 送信結果が確認できません）: card_id={card_id}")

    return True


# ─────────────────────────────────────────────
# 予約番号・有効期限の取得
# ─────────────────────────────────────────────

def get_reservation_info(driver, wait, card_id: str) -> tuple[str, str, str]:
    """
    jpmob から予約番号・有効期限・電話番号を取得して返す。
    例外が発生しても空文字を返し、処理全体は止めない。
    Returns: (電話番号, 予約番号, 有効期限)
    """
    try:
        url = f"https://console.jpmob.jp/sonet_cards/{card_id}?locale=ja"
        driver.get(url)

        # 電話番号をメイン情報から取得
        phone = ""
        try:
            phone = driver.find_element(By.XPATH,
                "//label[.//strong[normalize-space()='電話番号'] or normalize-space()='電話番号']/following-sibling::*[1]"
            ).text.strip()
        except Exception:
            pass

        # プランタブをクリック
        wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//a[@href='#sonet_plan' or contains(@href,'#sonet_plan')]")
        )).click()
        time.sleep(1)

        # MNP転出テーブルから予約番号と有効期限を取得
        yoyaku = ""
        expiry = ""
        try:
            mnp_cells = driver.find_elements(By.XPATH,
                "//h2[normalize-space()='MNP転出']/following-sibling::table[1]//td"
            )
            data = {}
            for i in range(0, len(mnp_cells) - 1, 2):
                data[mnp_cells[i].text.strip()] = mnp_cells[i + 1].text.strip()
            yoyaku = data.get("予約番号", "")
            expiry = data.get("有効期限", "")
        except Exception as e:
            print(f"[jpmob] 予約番号取得エラー (card_id={card_id}): {e}")

        return phone, yoyaku, expiry

    except Exception as e:
        print(f"[jpmob] カード情報取得エラー (card_id={card_id}): {type(e).__name__}: {e}")
        return "", "", ""


# ─────────────────────────────────────────────
# メイン関数
# ─────────────────────────────────────────────

def input_to_jpmob(records: list[dict]) -> list[dict]:
    """
    スプレッドシートのレコードをjpmobに入力し、割り当て情報を返す。
    申込回線数に応じて複数のSIMカードを1顧客に割り当てる。

    Returns:
        assignments: [{"record": ..., "sim_phone": ..., "card_id": ..., "entered_at": ...}, ...]
    """
    username = os.getenv("JPMOB_USERNAME")
    password = os.getenv("JPMOB_PASSWORD")

    if not all([username, password]):
        raise ValueError("[jpmob] .env の JPMOB_USERNAME / JPMOB_PASSWORD が未設定です")

    # ── 既処理済みカードIDを取得（二重処理防止）─────────────
    from assignment_sheet import get_processed_card_ids, get_card_ids_with_reservation
    processed_card_ids = get_processed_card_ids()

    # ── 予約番号記録済みカードIDを取得（有効期限切れ後の再処理・上書き防止）──
    # jpmobで有効期限切れになるとステータスが「開通済み」に戻るため、
    # 割り当てシートに予約番号が残っているカードは絶対に再処理しない。
    reserved_card_ids = get_card_ids_with_reservation()

    # ── スキップキャッシュ読み込み（開通日が古いカードを即スキップ）──
    skip_cache = _load_skip_cache()

    # ── 入力済みカードID読み込み（スプレッドシート書き込み失敗時の再試行防止）──
    entered_cards = _load_entered_cards()

    # ── ⑥ entered_cards.json の整理（蓄積防止）──────────────
    # assignment_sheet に記録済みのカードは entered_cards での追跡が不要なため削除する
    redundant = _entered_cards & (processed_card_ids | reserved_card_ids)
    if redundant:
        _entered_cards -= redundant
        try:
            with open(_ENTERED_CARDS_FILE, "w") as f:
                json.dump(
                    {"entered_card_ids": sorted(_entered_cards),
                     "updated_at": datetime.now().isoformat()},
                    f, indent=2,
                )
            print(f"[jpmob] entered_cards.json を整理: {len(redundant)} 件削除 → 残 {len(_entered_cards)} 件")
        except Exception as e:
            print(f"[jpmob] entered_cards.json 整理エラー: {e}")

    driver = create_driver(headless=True)
    wait   = WebDriverWait(driver, 15)

    try:
        login(driver, wait, username, password)

        # 開通済みカードを全件取得
        all_open_cards = get_open_cards(driver, wait)
        if not all_open_cards:
            print("[jpmob] 開通済みカードが見つかりません")
            return []

        # 既処理済みカード + 予約番号記録済み + スキップキャッシュ + 入力済みカード を除外
        exclude_ids = processed_card_ids | reserved_card_ids | skip_cache | entered_cards
        open_cards = [c for c in all_open_cards if c["card_id"] not in exclude_ids]
        skipped_total = len(all_open_cards) - len(open_cards)
        if skipped_total:
            print(
                f"[jpmob] 除外: {skipped_total} 件"
                f"（処理済み {len(processed_card_ids)} + キャッシュ {len(skip_cache & set(c['card_id'] for c in all_open_cards))}"
                f" + 入力済み {len(entered_cards & set(c['card_id'] for c in all_open_cards))}）"
                f" → 対象 {len(open_cards)} 件"
            )

        if not open_cards:
            print("[jpmob] 処理対象カードがありません（すべて処理済み or 開通日フィルター対象外）")
            return []

        card_index  = 0
        assignments = []

        for record in records:
            # 申込回線数（デフォルト1）
            try:
                num_lines = int(record.get("申込回線数", 1))
            except (ValueError, TypeError):
                num_lines = 1

            lines_assigned = 0
            while lines_assigned < num_lines:
                if card_index >= len(open_cards):
                    print("[jpmob] 開通済みカードが不足しています")
                    break

                card = open_cards[card_index]
                card_index += 1

                name = f"{record.get('姓（漢字）','')} {record.get('名（漢字）','')}".strip() \
                       or record.get('名前', '')
                print(f"[jpmob] 入力中: {name} → SIM {card['phone']} (card_id={card['card_id']})")

                entered = enter_user_info(driver, wait, card["card_id"], record)
                if not entered:
                    # スキップされた場合は次のカードで再試行
                    continue

                assignments.append({
                    "record":        record,
                    "sim_phone":     card["phone"],
                    "card_id":       card["card_id"],
                    "entered_at":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "yoyaku_number": "",
                    "expiry_date":   "",
                })
                lines_assigned += 1

        print(f"[jpmob] 入力完了: 合計 {len(assignments)} 件")

        # スキップキャッシュを保存（次回起動時に即スキップ）
        _save_skip_cache()

        return assignments

    except Exception as e:
        print(f"[jpmob] エラー: {e}")
        # エラー時もキャッシュは保存（途中まで判明したスキップを無駄にしない）
        _save_skip_cache()
        raise
    finally:
        driver.quit()


def fetch_reservations(assignments: list[dict]) -> list[dict]:
    """
    1時間後にjpmobへ再ログインし、各カードの予約番号・有効期限を取得する。
    assignments を更新して返す。
    """
    username = os.getenv("JPMOB_USERNAME")
    password = os.getenv("JPMOB_PASSWORD")

    driver = create_driver(headless=True)
    wait   = WebDriverWait(driver, 15)

    try:
        login(driver, wait, username, password)

        for a in assignments:
            # 既に予約番号取得済みならスキップ（再チェックで消えるのを防止）
            if a.get("yoyaku_number"):
                print(f"[jpmob] 予約番号取得済み（スキップ）: SIM {a['sim_phone']} → {a['yoyaku_number']}")
                continue

            card_id = a["card_id"]
            phone, yoyaku, expiry = get_reservation_info(driver, wait, card_id)

            if not a.get("sim_phone") and phone:
                a["sim_phone"] = phone
            if yoyaku:
                a["yoyaku_number"] = yoyaku
                a["expiry_date"]   = expiry
                print(f"[jpmob] 予約番号取得: SIM {a['sim_phone']} → {yoyaku} (有効期限: {expiry})")
            else:
                print(f"[jpmob] 予約番号未発行: SIM {a['sim_phone']} (card_id={card_id})")

        return assignments

    except Exception as e:
        print(f"[jpmob] 予約番号取得エラー: {e}")
        raise
    finally:
        driver.quit()
