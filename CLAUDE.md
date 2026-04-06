# ikedamobile SIM自動化システム

## 概要

SIMカード申し込みの処理を自動化するシステム。
専用フォーム（Stripe決済付き）で受け付けた申し込みに対して、jpmob管理コンソールへの顧客情報入力・MNP予約番号取得・メール送信を全自動で行う。

## 処理フロー（main.py）

```
Step 1: スプレッドシートから未処理の申し込みを読み込み
        └ 専用フォーム（申し込み管理タブ）から取得
        └ 重複チェック（メールアドレスで同一人物を検出、二重処理を防止）

Step 2: jpmob管理コンソールに顧客情報を自動入力（8:00〜20:00のみ）
        └ 開通済みSIMカードの一覧を取得
        └ 申込回線数に応じてSIMカードを割り当て
        └ 各カードの「ユーザー情報変更」フォームに6項目を入力:
          姓（フリガナ）/ 名（フリガナ）/ 姓（漢字）/ 名（漢字）/ 生年月日 / 性別
        └ 全6項目が揃っていないレコードはスキップ（誤登録防止）
        └ 性別が不明な場合はデフォルト適用せずスキップ（誤った性別での登録を防止）
        └ 送信後にモーダルの閉鎖を検証し、エラー時はスクリーンショットを保存

Step 3: 割り当て情報をスプレッドシート（「割り当て」タブ）に記録
Step 3.5: 申し込みの処理済みフラグを更新

Step 4: 60分待機（jpmob側でMNP予約番号が発行されるのを待つ）

Step 5: jpmobから予約番号・有効期限を取得（最大6回リトライ、30分間隔）
        └ 取得済みの予約番号は再チェック時にスキップ（上書き消失を防止）

Step 6: 割り当てスプレッドシートに予約番号・有効期限を更新

Step 7: 予約番号が取得できた顧客にメール送信
```

## ディレクトリ構成

```
jpmob-automation/
├── main.py                 # メイン処理（上記フロー全体を統括）
├── jpmob_automator.py      # Selenium による jpmob 自動入力・予約番号取得
├── sheets_reader.py        # Googleスプレッドシート読み込み・更新
├── application_sheet.py    # 専用フォーム「申し込み管理」タブの管理
├── assignment_sheet.py     # 「割り当て」タブの管理（SIM↔顧客の紐付け記録）
├── gmail_sender.py         # Gmail API でメール送信
├── reminder.py             # フォーム記入リマインダー送信
├── watcher.py              # main.py の監視・自動再起動
├── webhook.py              # Stripe Webhook 受信サーバー
├── retry_send.py           # 予約番号未取得分の再送信
├── mark_all_processed.py   # 既存レコードを一括「処理済み」にするユーティリティ
├── drive_uploader.py       # Google Drive への本人確認書類アップロード
├── requirements.txt        # 依存ライブラリ
├── .env                    # 環境変数（Git管理外）
├── .env.example            # .env のテンプレート
├── credentials.json        # Google OAuth認証情報（Git管理外）
└── token.json              # Google OAuthトークン（Git管理外）
```

## セットアップ手順

### 1. Python仮想環境

```bash
cd jpmob-automation
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 環境変数

```bash
cp .env.example .env
# .env を編集して必要な値を設定
```

### 3. Google OAuth認証

- Google Cloud Console でOAuth 2.0クライアントIDを作成
- `credentials.json` をダウンロードして `jpmob-automation/` に配置
- 初回実行時にブラウザで認証 → `token.json` が自動生成される

### 4. Chromeのインストール

Selenium が Chrome を使用する。ChromeDriver は `webdriver-manager` が自動インストール。

## 実行方法

```bash
cd jpmob-automation
source venv/bin/activate

# メイン処理（jpmob入力 → 予約番号取得 → メール送信）
python main.py

# 監視モード（main.py の完了を検知して自動再起動）
python watcher.py

# フォーム記入リマインダー送信
python reminder.py

# 初回セットアップ: 既存レコードを全て処理済みにする
python mark_all_processed.py
```

## 主な環境変数

| 変数名 | 説明 | 例 |
|---|---|---|
| `JPMOB_USERNAME` | jpmob ログインメール | `user@gmail.com` |
| `JPMOB_PASSWORD` | jpmob パスワード | |
| `SPREADSHEET_ID` | スプレッドシートのID | |
| `SHEET_NAME` | シート名 | `フォームの回答 1` |
| `GMAIL_SENDER` | 送信元Gmail | `info@example.com` |
| `STRIPE_SECRET_KEY` | Stripe シークレットキー | `sk_live_xxx` |
| `SEND_DELAY_SECONDS` | 予約番号取得までの待機秒数 | `3600`（60分） |
| `JPMOB_OPEN_DATE_CUTOFF` | 処理対象の開通日下限 | `2026-03-11` |
| `STATUS_COLUMN` | 処理済み判定の列名 | `予約番号案内` |
| `RETRY_INTERVAL_SECONDS` | 予約番号リトライ間隔（秒） | `1800`（30分） |
| `MAX_RETRIES` | 予約番号リトライ回数 | `6` |

## スプレッドシート構成

### 「申し込み管理」タブ（専用フォームからの申し込み）

| 列名 | 説明 |
|---|---|
| タイムスタンプ | 申し込み日時 |
| 姓（漢字）/ 名（漢字） | 漢字氏名 |
| 姓（フリガナ）/ 名（フリガナ） | カタカナ氏名 |
| 生年月日 | YYYY-MM-DD 形式 |
| 性別 | `female` または `male` |
| メールアドレス | 通知先 |
| プラン / 申込回線数 | 申し込み内容 |
| 決済金額 / 決済ID | Stripe決済情報 |
| 予約番号案内 | 空=未処理 / TRUE=処理済み |

### 「割り当て」タブ（SIMカード↔顧客の紐付け）

| 列名 | 説明 |
|---|---|
| 顧客名 / メールアドレス / フリガナ / 性別 | 顧客情報 |
| SIM電話番号 / カードID | 割り当てたSIM |
| 予約番号 / 有効期限 | MNP予約番号 |
| メール送信済み | 送信ステータス |

## 安全機構

| 機構 | 説明 | ファイル |
|---|---|---|
| **重複チェック** | メールアドレスで同一人物を検出し二重処理を防止 | `main.py` |
| **6項目必須バリデーション** | 全フィールドが揃わないと登録しない | `jpmob_automator.py` |
| **性別デフォルト廃止** | 性別不明時はデフォルト適用せずスキップ | `jpmob_automator.py` |
| **送信後検証** | モーダル閉鎖確認・エラーメッセージ検出・スクリーンショット保存 | `jpmob_automator.py` |
| **入力済みカード追跡** | `entered_cards.json` で即記録し、スプレッドシート書き込み失敗時の再入力を防止 | `jpmob_automator.py` |
| **スキップキャッシュ** | 開通日が古いカードをキャッシュし、次回以降の Selenium スキャンを省略 | `jpmob_automator.py` |
| **予約番号上書き防止** | 取得済みの予約番号は再チェック時にスキップ | `jpmob_automator.py` |
| **有効期限切れ再処理防止** | 割り当てシートに予約番号が記録済みのカードは、jpmob側で「開通済み」に戻っても絶対に再処理しない（`get_card_ids_with_reservation()`） | `assignment_sheet.py`, `jpmob_automator.py` |
| **ヘッダー正規化** | スプレッドシートのヘッダーに含まれる改行・空白を除去 | `sheets_reader.py` |
| **時間制限** | 8:00〜20:00のみjpmob入力を実行 | `main.py` |
| **短いタイムアウト** | 入力済みカードを3秒で判定（15秒待たない） | `jpmob_automator.py` |

## 定期実行（本番運用）

watcher.py による常時監視、または cron で定期実行:

```cron
# 毎日 9:00 にリマインダーチェック
0 9 * * * /path/to/venv/bin/python /path/to/reminder.py >> /path/to/reminder.log 2>&1

# 毎日 10:00 にメイン処理
0 10 * * * /path/to/venv/bin/python /path/to/main.py >> /path/to/main.log 2>&1
```

## 横展開時の手順

別の MVNO サービスで同様のシステムを構築する場合:

1. **jpmob_automator.py を差し替え**: 対象サイトの URL・セレクタ・フォーム構造に合わせる
2. **application_sheet.py のヘッダーを調整**: 収集する顧客情報に合わせる
3. **assignment_sheet.py のヘッダーを調整**: 記録する割り当て情報に合わせる
4. **gmail_sender.py のテンプレートを変更**: メール文面・件名を変更
5. **.env を設定**: 新しいサービスの認証情報を設定
6. **sheets_reader.py はそのまま使える**: Google OAuth・スプレッドシート読み書きは共通

## 依存ライブラリ

| ライブラリ | 用途 |
|---|---|
| selenium | 管理コンソールへの自動入力 |
| webdriver-manager | ChromeDriverの自動管理 |
| gspread | Googleスプレッドシートの読み書き |
| google-auth / google-api-python-client | Google OAuth認証・Gmail API |
| stripe | Stripe 決済情報の取得 |
| python-dotenv | .env から環境変数を読み込む |
| flask | Webhook受信サーバー |

## jpmob 管理コンソール 操作詳細

スクリーンショットで確認・指示した画面構造を記録しておく。変更時はここを更新すること。

### URL

| 用途 | URL |
|---|---|
| ログイン | `https://console.jpmob.jp/admin_users/sign_in` |
| カード一覧 | `https://console.jpmob.jp/sonet_cards/iot_external_index` |
| カード詳細 | `https://console.jpmob.jp/sonet_cards/{card_id}?locale=ja` |

### ログイン画面

| 項目 | セレクタ |
|---|---|
| メールアドレス | `#admin_user_email` |
| パスワード | `#admin_user_password` |
| 送信ボタン | `input[type='submit']` |

### カード一覧画面（`iot_external_index`）

- 状態フィルター: `<select>` に「開通済み」オプションを含む要素を XPath で特定して選択
  - XPath: `//select[.//option[normalize-space(text())='開通済み']]`
- 全件表示: `<select>` の `value='9999999'` オプションを選択
- カードID・電話番号の収集: `table tbody tr td a` のリンクから `href` の `/sonet_cards/{card_id}` パターンでカードIDを抽出

### jpmob のステータス仕様（実機確認済み）

- MNP予約番号の**有効期限が切れると、ステータスが「MNP転出中」ではなく「開通済み」に戻る**
- これにより有効期限切れカードが新規カードと区別できなくなるため、**割り当てシートの予約番号列を再処理禁止の判定基準**としている
- 電話番号 8015150572 で実機確認済み（2026年4月時点）

### 処理対象の絞り込み条件

**発送日（開通日）が 2026年3月11日以降のカードのみ処理対象。**

- 環境変数 `JPMOB_OPEN_DATE_CUTOFF`（デフォルト: `2026-03-11`）で制御
- カード詳細ページの「開通日」フィールドを取得して比較
- 開通日がカットオフより前のカードはスキップし `skipped_cards.json` にキャッシュ（次回以降の Selenium スキャンを省略）

### カード詳細画面

- **プランタブ**: `a[href='#sonet_plan']` をクリックして切り替え
- **カタカナ更新ボタン**（ユーザー情報入力モーダルのトリガー）:
  - セレクタ: `a[data-target='#update_mnp_user_info']`
  - ボタンが表示されない場合 = 既に情報入力済み（3秒タイムアウトで判定）
- **開通日の取得**:
  - XPath: `//label[.//strong[normalize-space()='開通日']]/following-sibling::div[1]//p[1]`
  - 形式: `2026年03月13日`
- **状態の取得**:
  - XPath（優先順）:
    1. `//dt[normalize-space()='状態']/following-sibling::dd[1]`
    2. `//th[normalize-space()='状態']/following-sibling::td[1]`
    3. `//td[normalize-space()='状態']/following-sibling::td[1]`

### ユーザー情報入力モーダル（`#update_mnp_user_info`）

モーダルID: `update_mnp_user_info`

| フィールド | HTML ID | 内容 |
|---|---|---|
| 姓（フリガナ） | `last_name_kana` | カタカナ |
| 名（フリガナ） | `first_name_kana` | カタカナ |
| 姓（漢字） | `last_name` | 漢字 |
| 名（漢字） | `first_name` | 漢字 |
| 生年月日 | `birthday` | YYYY-MM-DD |
| 性別 | `sex` | `male` / `female`（`<select>`） |

- 送信ボタン: `#update_mnp_user_info input[type='submit']`
- 送信後の検証: モーダルが閉じているか（`is_displayed()` が False）を確認

### MNP予約番号の取得

カード詳細画面のプランタブ内「MNP転出」テーブル（`h2` 見出しの直後の `table`）から取得:

```
//h2[normalize-space()='MNP転出']/following-sibling::table[1]//td
```

テーブルは `キー | 値` の2列構造。取得するキー: `予約番号`、`有効期限`

## 注意事項

- `.env`, `credentials.json`, `token.json` は機密情報のため Git 管理外
- `entered_cards.json`, `skipped_cards.json` は実行時キャッシュ（Git管理外）
- `debug_screenshots/` はエラー時のスクリーンショット（Git管理外）
- jpmob サイト: `console.jpmob.jp`
