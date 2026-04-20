"""カード詳細ページのHTML構造を確認する（デバッグ用）"""
import os
import re
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv

load_dotenv()

LIST_URL  = "https://console.jpmob.jp/sonet_cards/iot_external_index"
LOGIN_URL = "https://console.jpmob.jp/admin_users/sign_in"

def create_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1600,1200")
    service = Service(ChromeDriverManager().install())
    driver  = webdriver.Chrome(service=service, options=options)
    driver.implicitly_wait(10)
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

def main():
    driver = create_driver()
    wait   = WebDriverWait(driver, 15)
    try:
        login(driver, wait)

        # 最初の開通済みカードを1件だけ取得
        driver.get(LIST_URL)
        time.sleep(2)
        status_select = wait.until(EC.presence_of_element_located(
            (By.XPATH, "//select[.//option[normalize-space(text())='開通済み']]")
        ))
        Select(status_select).select_by_visible_text("開通済み")
        time.sleep(2)

        links = driver.find_elements(By.CSS_SELECTOR, "table tbody tr td a")
        first_card = None
        for link in links:
            href = link.get_attribute("href") or ""
            text = link.text.strip()
            m = re.search(r"/sonet_cards/(\d+)", href)
            if m and text:
                first_card = {"phone": text, "card_id": m.group(1)}
                break

        if not first_card:
            print("カードが見つかりません")
            return

        print(f"\n最初のカード: {first_card}")

        # カード詳細ページに移動
        url = f"https://console.jpmob.jp/sonet_cards/{first_card['card_id']}?locale=ja"
        driver.get(url)
        time.sleep(2)

        # ── ページ内の全テキストラベルを取得 ──────────────────
        print("\n=== ページ内の全 label/strong/dt/th テキスト ===")
        for tag in ["label", "strong", "dt", "th", "td"]:
            elements = driver.find_elements(By.TAG_NAME, tag)
            for el in elements:
                txt = el.text.strip()
                if txt and len(txt) < 30:
                    print(f"  <{tag}>: {txt!r}")

        # ── ページのテキスト全体（短縮版）────────────────────
        print("\n=== ページのテキスト全体（先頭3000文字）===")
        body_text = driver.find_element(By.TAG_NAME, "body").text
        print(body_text[:3000])

        # ── HTMLソースの一部（カード情報っぽい部分）────────────
        print("\n=== ページソース（先頭5000文字）===")
        src = driver.page_source
        # メインコンテンツっぽい部分を探す
        start = src.find('<div class="container')
        if start == -1:
            start = src.find('<main')
        if start == -1:
            start = 0
        print(src[start:start+5000])

    finally:
        driver.quit()

if __name__ == "__main__":
    main()
