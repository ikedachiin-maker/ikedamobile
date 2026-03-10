"""
2025年開通済みカードのICCID・電話番号抽出スクリプト
対象: 2025年6月・8月・10月・12月 開通の13件
"""
import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv

load_dotenv()

LOGIN_URL = "https://console.jpmob.jp/admin_users/sign_in"

# 前回の調査で確認した2025年開通カード（月ごと）
TARGET_CARDS = [
    # 2025年06月
    {"month": "2025年06月04日", "card_id": "346070",  "phone": "08024490599"},
    # 2025年08月
    {"month": "2025年08月05日", "card_id": "370525",  "phone": "09058998100"},
    {"month": "2025年08月05日", "card_id": "370526",  "phone": "09058998348"},
    {"month": "2025年08月05日", "card_id": "370527",  "phone": "08085251843"},
    # 2025年10月
    {"month": "2025年10月01日", "card_id": "405277",  "phone": "08029264343"},
    {"month": "2025年10月01日", "card_id": "405297",  "phone": "08082369082"},
    # 2025年12月
    {"month": "2025年12月09日", "card_id": "434396",  "phone": "09085792294"},
    {"month": "2025年12月26日", "card_id": "452848",  "phone": "09040808731"},
    {"month": "2025年12月26日", "card_id": "452850",  "phone": "08027767631"},
    {"month": "2025年12月26日", "card_id": "452857",  "phone": "09040808193"},
    {"month": "2025年12月26日", "card_id": "452870",  "phone": "08082860301"},
    {"month": "2025年12月26日", "card_id": "452871",  "phone": "08010319401"},
    {"month": "2025年12月26日", "card_id": "452872",  "phone": "08082846724"},
]


def create_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,900")
    service = Service(ChromeDriverManager().install())
    driver  = webdriver.Chrome(service=service, options=options)
    driver.implicitly_wait(8)
    return driver


def login(driver, wait):
    username = os.getenv("JPMOB_USERNAME")
    password = os.getenv("JPMOB_PASSWORD")
    driver.get(LOGIN_URL)
    wait.until(EC.presence_of_element_located((By.ID, "admin_user_email"))).send_keys(username)
    driver.find_element(By.ID, "admin_user_password").send_keys(password)
    driver.find_element(By.CSS_SELECTOR, "input[type='submit']").click()
    wait.until(EC.url_changes(LOGIN_URL))
    time.sleep(1)
    print("[login] OK")


def get_label_value(driver, label_text: str) -> str:
    """<label><strong>ラベル</strong></label> の次の <div><p>値</p></div> を取得"""
    try:
        xpath = (
            f"//label[.//strong[normalize-space()='{label_text}']]"
            f"/following-sibling::div[1]//p[1]"
        )
        return driver.find_element(By.XPATH, xpath).text.strip()
    except Exception:
        return ""


def main():
    driver = create_driver()
    wait   = WebDriverWait(driver, 15)

    try:
        login(driver, wait)

        results = []
        print(f"\n対象 {len(TARGET_CARDS)} 件のICCIDを取得中...")

        for card in TARGET_CARDS:
            url = f"https://console.jpmob.jp/sonet_cards/{card['card_id']}?locale=ja"
            driver.get(url)
            time.sleep(1)

            iccid = get_label_value(driver, "ICCID")
            results.append({**card, "iccid": iccid})
            print(f"  card_id={card['card_id']} / 電話={card['phone']} / ICCID={iccid}")

        # ── 結果表示 ─────────────────────────────────────────
        print("\n" + "=" * 75)
        print("  2025年開通済みカード一覧（ICCID・電話番号）")
        print("=" * 75)

        current_month = ""
        for r in results:
            month_label = r["month"][:7]  # "2025年06月"
            if month_label != current_month:
                print(f"\n  ▼ {month_label} 開通")
                print(f"  {'電話番号':<15}  {'ICCID':<20}  card_id")
                print(f"  {'-'*55}")
                current_month = month_label
            print(f"  {r['phone']:<15}  {r['iccid'] or '（取得失敗）':<20}  {r['card_id']}")

        print("\n" + "=" * 75)
        print(f"  合計: {len(results)} 件")
        print("=" * 75)

        # タブ区切り（コピペ用）
        print("\n── コピペ用（タブ区切り）──")
        print("開通日\t電話番号\tICCID\tcard_id")
        for r in results:
            print(f"{r['month']}\t{r['phone']}\t{r['iccid']}\t{r['card_id']}")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
