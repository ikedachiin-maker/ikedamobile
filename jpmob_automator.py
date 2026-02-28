"""jpmob 管理コンソールへの自動入力モジュール（Selenium）"""
import os
import re
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


def normalize_birthday(birthday_str: str) -> str:
    """生年月日を YYYY-MM-DD 形式に正規化する"""
    s = (birthday_str or "").strip()
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
    """スプレッドシートの性別（男性/女性）をjpmobの値（male/female）に変換する"""
    sex_raw = record.get("性別", "").strip()
    if sex_raw == "女性":
        return "female"
    if sex_raw == "男性":
        return "male"
    # 未入力・不明の場合は環境変数のデフォルト値を使用
    return os.getenv("JPMOB_DEFAULT_SEX", "male")


def enter_user_info(driver, wait, card_id: str, record: dict) -> None:
    """1枚のSIMカードにスプレッドシートの顧客情報を入力する"""
    url = f"https://console.jpmob.jp/sonet_cards/{card_id}?locale=ja"
    driver.get(url)

    # プランタブをクリック
    wait.until(EC.element_to_be_clickable(
        (By.XPATH, "//a[@href='#sonet_plan' or contains(@href,'#sonet_plan')]")
    )).click()
    time.sleep(1)

    # カタカナ更新ボタン（モーダルトリガー）をクリック
    katakana_btn = wait.until(EC.element_to_be_clickable(
        (By.CSS_SELECTOR, "a[data-target='#update_mnp_user_info']")
    ))
    driver.execute_script("arguments[0].scrollIntoView(true);", katakana_btn)
    time.sleep(0.5)
    katakana_btn.click()

    # モーダルが開くまで待機
    wait.until(EC.visibility_of_element_located((By.ID, "last_name_kana")))

    # フォームの各列から直接取得（姓・名は別々の列）
    last_kana  = record.get("姓（フリガナ）", "").strip()
    first_kana = record.get("名（フリガナ）", "").strip()
    last_kanji  = record.get("姓（漢字）", "").strip()
    first_kanji = record.get("名（漢字）", "").strip()
    birthday = normalize_birthday(record.get("生年月日", ""))
    sex = get_sex_value(record)

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

    # 更新ボタンをクリック
    driver.find_element(By.CSS_SELECTOR,
        "#update_mnp_user_info input[type='submit']"
    ).click()
    time.sleep(2)

    print(f"[jpmob] 入力完了: {record.get('名前','')} → SIM {driver.find_elements(By.XPATH, '//label[contains(.,\"電話番号\")]/following-sibling::*') and card_id}")


# ─────────────────────────────────────────────
# 予約番号・有効期限の取得
# ─────────────────────────────────────────────

def get_reservation_info(driver, wait, card_id: str) -> tuple[str, str, str]:
    """
    jpmob から予約番号・有効期限・電話番号を取得して返す
    Returns: (電話番号, 予約番号, 有効期限)
    """
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

    driver = create_driver(headless=False)
    wait   = WebDriverWait(driver, 15)

    try:
        login(driver, wait, username, password)

        # 開通済みカードを全件取得
        open_cards = get_open_cards(driver, wait)
        if not open_cards:
            print("[jpmob] 開通済みカードが見つかりません")
            return []

        card_index  = 0
        assignments = []

        for record in records:
            # 申込回線数（デフォルト1）
            try:
                num_lines = int(record.get("申込回線数", 1))
            except (ValueError, TypeError):
                num_lines = 1

            for _ in range(num_lines):
                if card_index >= len(open_cards):
                    print("[jpmob] 開通済みカードが不足しています")
                    break

                card = open_cards[card_index]
                card_index += 1

                print(f"[jpmob] 入力中: {record.get('名前','')} → SIM {card['phone']} (card_id={card['card_id']})")
                enter_user_info(driver, wait, card["card_id"], record)

                assignments.append({
                    "record":     record,
                    "sim_phone":  card["phone"],
                    "card_id":    card["card_id"],
                    "entered_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "yoyaku_number": "",
                    "expiry_date":   "",
                })

        print(f"[jpmob] 入力完了: 合計 {len(assignments)} 件")
        return assignments

    except Exception as e:
        print(f"[jpmob] エラー: {e}")
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

    driver = create_driver(headless=False)
    wait   = WebDriverWait(driver, 15)

    try:
        login(driver, wait, username, password)

        for a in assignments:
            card_id = a["card_id"]
            phone, yoyaku, expiry = get_reservation_info(driver, wait, card_id)

            if not a.get("sim_phone") and phone:
                a["sim_phone"] = phone
            a["yoyaku_number"] = yoyaku
            a["expiry_date"]   = expiry

            if yoyaku:
                print(f"[jpmob] 予約番号取得: SIM {a['sim_phone']} → {yoyaku} (有効期限: {expiry})")
            else:
                print(f"[jpmob] 予約番号未発行: SIM {a['sim_phone']} (card_id={card_id})")

        return assignments

    except Exception as e:
        print(f"[jpmob] 予約番号取得エラー: {e}")
        raise
    finally:
        driver.quit()
