"""
開通済みカード一覧調査スクリプト（改良版）
- jpmob にログインし「開通済み」カードを全件取得
- 各カードの詳細ページから：電話番号・開通日を抽出
  ※氏名は jpmob 詳細ページには表示されない（カタカナ更新モーダルでのみ入力可能）
- 結果を表形式で表示する（一時利用スクリプト）
"""
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
    options.add_argument("--window-size=1280,900")
    service = Service(ChromeDriverManager().install())
    driver  = webdriver.Chrome(service=service, options=options)
    driver.implicitly_wait(8)
    return driver


def login(driver, wait):
    username = os.getenv("JPMOB_USERNAME")
    password = os.getenv("JPMOB_PASSWORD")
    print(f"[login] {username} でログイン中...")
    driver.get(LOGIN_URL)
    wait.until(EC.presence_of_element_located((By.ID, "admin_user_email"))).send_keys(username)
    driver.find_element(By.ID, "admin_user_password").send_keys(password)
    driver.find_element(By.CSS_SELECTOR, "input[type='submit']").click()
    wait.until(EC.url_changes(LOGIN_URL))
    time.sleep(1)
    print("[login] ログイン完了")


def get_open_card_list(driver, wait):
    """開通済みカード一覧（電話番号 + card_id）を取得"""
    driver.get(LIST_URL)
    time.sleep(2)

    status_select = wait.until(EC.presence_of_element_located(
        (By.XPATH, "//select[.//option[normalize-space(text())='開通済み']]")
    ))
    Select(status_select).select_by_visible_text("開通済み")
    time.sleep(2)

    try:
        per_page = driver.find_element(By.XPATH, "//select[.//option[@value='9999999']]")
        Select(per_page).select_by_value("9999999")
        time.sleep(2)
    except Exception:
        pass

    links = driver.find_elements(By.CSS_SELECTOR, "table tbody tr td a")
    cards = []
    for link in links:
        href = link.get_attribute("href") or ""
        text = link.text.strip()
        m = re.search(r"/sonet_cards/(\d+)", href)
        if m and text:
            cards.append({"phone": text, "card_id": m.group(1)})

    print(f"[list] 開通済みカード: {len(cards)} 件")
    return cards


def get_label_value(driver, label_text: str) -> str:
    """
    jpmob のカード詳細ページのフィールド値を取得する。
    HTML 構造: <label><strong>ラベル</strong></label>  <div><p>値</p></div>
    """
    try:
        xpath = (
            f"//label[.//strong[normalize-space()='{label_text}']]"
            f"/following-sibling::div[1]//p[1]"
        )
        el = driver.find_element(By.XPATH, xpath)
        return el.text.strip()
    except Exception:
        return ""


def get_card_open_date(driver, wait, card_id: str) -> str:
    """カード詳細ページから開通日を取得"""
    url = f"https://console.jpmob.jp/sonet_cards/{card_id}?locale=ja"
    driver.get(url)
    time.sleep(1)
    return get_label_value(driver, "開通日")


def main():
    driver = create_driver()
    wait   = WebDriverWait(driver, 15)

    try:
        login(driver, wait)
        cards = get_open_card_list(driver, wait)

        if not cards:
            print("開通済みカードが見つかりませんでした。")
            return

        results = []
        print(f"\n各カードの開通日を取得中（全 {len(cards)} 件）...")

        for i, card in enumerate(cards, 1):
            open_date = get_card_open_date(driver, wait, card["card_id"])
            results.append({
                "No":      i,
                "電話番号": card["phone"],
                "card_id": card["card_id"],
                "開通日":  open_date,
            })
            if i % 10 == 0 or i == len(cards):
                print(f"  {i}/{len(cards)} 件完了...")

        # ── 結果を表示 ────────────────────────────────────────
        print("\n" + "=" * 65)
        print(f"  開通済みカード一覧  （合計: {len(results)} 件）")
        print("=" * 65)
        print(f"{'No':>3}  {'電話番号':<15}  {'開通日':<15}  card_id")
        print("-" * 65)

        # 開通日でソート（新しい順）
        results_sorted = sorted(
            results,
            key=lambda r: r["開通日"] or "0000",
            reverse=True
        )
        for r in results_sorted:
            open_date_disp = r["開通日"] or "（不明）"
            print(f"{r['No']:>3}  {r['電話番号']:<15}  {open_date_disp:<15}  {r['card_id']}")

        print("=" * 65)

        # 開通日の集計
        with_date    = [r for r in results if r["開通日"]]
        without_date = [r for r in results if not r["開通日"]]
        print(f"\n  開通日あり : {len(with_date)} 件")
        print(f"  開通日なし : {len(without_date)} 件")

        # 開通月ごとの集計
        print("\n  ── 開通月ごとの件数 ──")
        month_count = {}
        for r in results:
            d = r["開通日"]
            if d:
                # "2025年06月04日" → "2025年06月"
                m = re.match(r"(\d{4}年\d{2}月)", d)
                key = m.group(1) if m else d[:7]
            else:
                key = "（不明）"
            month_count[key] = month_count.get(key, 0) + 1

        for month in sorted(month_count.keys()):
            print(f"    {month}: {month_count[month]:>3} 件")

        # 注記
        print("\n  ※ jpmob の詳細ページには氏名フィールドがありません。")
        print("    氏名はカタカナ更新モーダル（プランタブ）で入力するため、")
        print("    現時点では「未入力」の状態がすべての処理待ちカードです。")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
