# jpmob-automation

SIMカード申し込み処理を全自動化するシステム。
専用フォーム（Stripe決済付き）で受け付けた申し込みに対して、jpmob管理コンソールへの顧客情報入力・MNP予約番号取得・メール送信を自動で行う。

---

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

---

## アーキテクチャ

```
お客様
  └── https://ikedamobile.com  ← Cloudflare DNS
           │
           ▼
      Railway（24時間稼働）
      ・LP・申し込みフォーム配信
      ・Stripe Webhook 受信
      ・スプレッドシートへの申込記録
      ・本人確認書類を Google Drive に保存
           │
           │（スプレッドシートに記録）
           ▼
      Mac mini（watcher.py 常駐監視）
      ・5分ごとにスプレッドシートをチェック
      ・jpmob への顧客情報入力
      ・予約番号取得 → お客様にメール送信
```

---

## ファイル構成

```
jpmob-automation/
├── main.py               # メイン処理（上記フロー全体を統括）
├── webhook.py            # Flask サーバー（LP配信・フォームAPI・Stripe Webhook）
├── jpmob_automator.py    # Selenium による jpmob 自動入力・予約番号取得
├── sheets_reader.py      # Google スプレッドシート読み込み・更新
├── application_sheet.py  # 「申し込み管理」タブの管理（専用フォーム用）
├── assignment_sheet.py   # 「割り当て」タブの管理（カードID・予約番号の記録）
├── gmail_sender.py       # Gmail API でメール送信
├── reminder.py           # フォーム記入リマインダー送信
├── watcher.py            # 常駐監視（5分ごとにスプレッドシートをチェック → main.py を自動起動）
├── retry_send.py         # 予約番号未取得分の再送信
├── drive_uploader.py     # Google Drive への本人確認書類アップロード（Railway用）
├── mark_all_processed.py # 既存レコードを一括「処理済み」にするユーティリティ
├── check_open_cards.py   # 開通済みカード調査（運用管理用）
├── requirements.txt      # 依存ライブラリ
├── .env                  # 環境変数（Git管理外）
├── .env.example          # .env のテンプレート
├── credentials.json      # Google OAuth認証情報（Git管理外）
├── token.json            # Google OAuthトークン（Git管理外・初回自動生成）
└── venv/                 # Python 仮想環境（Git管理外）

lp/
├── index.html            # 申し込み LP
└── form.html             # 専用申し込みフォーム（Stripe Elements 統合）
```

---

## 安全機構

| 機構 | 説明 | ファイル |
|---|---|---|
| **重複チェック** | メールアドレスで同一人物を検出し二重処理を防止。専用フォームを優先 | `main.py` |
| **6項目必須バリデーション** | フリガナ・漢字・生年月日・性別の全6項目が揃わないと登録しない | `jpmob_automator.py` |
| **性別デフォルト廃止** | 性別不明時はデフォルト適用せずスキップ（誤った性別での登録を防止） | `jpmob_automator.py` |
| **送信後検証** | フォーム送信後にモーダル閉鎖を確認。エラー時はスクリーンショットを自動保存 | `jpmob_automator.py` |
| **入力済みカード追跡** | `entered_cards.json` で即記録し、スプレッドシート書き込み失敗時の再入力を防止 | `jpmob_automator.py` |
| **スキップキャッシュ** | 開通日が古いカードをキャッシュし、次回以降の Selenium スキャンを省略 | `jpmob_automator.py` |
| **予約番号上書き防止** | 取得済みの予約番号は再チェック時にスキップ（リトライで消失しない） | `jpmob_automator.py` |
| **ヘッダー正規化** | スプレッドシートのヘッダーに含まれる改行・空白を除去 | `sheets_reader.py` |
| **時間制限** | 8:00〜20:00のみjpmob入力を実行 | `main.py` |
| **短いタイムアウト** | 入力済みカードを3秒で判定（15秒待たない） | `jpmob_automator.py` |
| **デバッグログ** | 入力データと実際のフィールド値を毎回ログ出力（問題の早期発見） | `jpmob_automator.py` |

---

## セットアップ手順

### 1. 仮想環境

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

| ファイル | 取得方法 |
|---------|---------|
| `credentials.json` | Google Cloud Console > 認証情報 > OAuth 2.0 クライアントID をダウンロード |
| `token.json` | 初回 `python main.py` 実行時にブラウザ認証で自動生成 |

### 4. Chrome

Selenium が Chrome を使用。ChromeDriver は `webdriver-manager` が自動インストール。

---

## 実行方法

```bash
cd jpmob-automation
source venv/bin/activate

# メイン処理（jpmob入力 → 予約番号取得 → メール送信）
python main.py

# 常駐監視（5分ごとにチェック → main.py を自動起動）
python watcher.py

# フォーム記入リマインダー送信
python reminder.py

# 初回: 既存レコードを全て処理済みにする
python mark_all_processed.py
```

---

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

---

## スプレッドシート構成

| タブ名 | 用途 | 書き込み元 |
|--------|------|-----------|
| 申し込み管理 | 専用フォームからの申し込み | webhook.py |
| 割り当て | SIMカード↔顧客の紐付け・予約番号・送信状況 | main.py |

### 「申し込み管理」タブ

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

### 「割り当て」タブ

| 列名 | 説明 |
|---|---|
| 顧客名 / メールアドレス / フリガナ / 性別 | 顧客情報 |
| SIM電話番号 / カードID | 割り当てたSIM |
| 予約番号 / 有効期限 | MNP予約番号（Step 5で取得） |
| メール送信済み | 送信ステータス |

---

## 常駐監視（watcher.py）

```
watcher.py（Mac 上で常駐）
  │
  │  5分ごとにスプレッドシートを確認
  ▼
  未処理レコードあり？ → main.py をサブプロセスで起動
```

- **チェック間隔**: 5分（`WATCHER_INTERVAL_SECONDS` で変更可）
- **稼働時間帯**: 8:00〜20:00
- **重複防止**: main.py 実行中は次の起動をブロック

### launchd で自動起動（Mac）

```bash
launchctl load ~/Library/LaunchAgents/com.ikedamobile.watcher.plist    # 開始
launchctl unload ~/Library/LaunchAgents/com.ikedamobile.watcher.plist  # 停止
```

---

## 本番環境

| 項目 | 値 |
|------|-----|
| サービスURL | https://ikedamobile.com |
| Railway | web-production-1398a.up.railway.app |
| ドメイン | Cloudflare Registrar（ikedamobile.com） |
| Stripe Webhook | https://ikedamobile.com/webhook |

### Railway 設定

- **リポジトリ**: ikedachiin-maker/ikedamobile
- **Root Directory**: `/`（空欄）
- **起動コマンド**: `gunicorn --bind 0.0.0.0:$PORT --workers 1 --timeout 120 webhook:app`
- `GOOGLE_CREDENTIALS_JSON` / `GOOGLE_TOKEN_JSON` は JSON の中身を環境変数に設定

---

## Stripe 料金設定

| プラン | 単価（1回線あたり） |
|--------|------------------|
| consul（コンサル）| ¥3,000 |
| online（オンライン）| ¥3,300 |
| general（一般）| ¥3,600 |

---

## トラブルシューティング

### ヘルスチェック

```
https://ikedamobile.com/api/health
```

Stripe・Google認証・Google Drive の接続状況を一括確認可能。

### よくある問題

| 症状 | 対処 |
|------|------|
| jpmob にログインできない | `.env` の `JPMOB_USERNAME` / `JPMOB_PASSWORD` を確認 |
| スプレッドシートに書き込めない | `rm token.json` → `python main.py` で再認証 |
| Stripe 決済が通らない | `.env` の `STRIPE_SECRET_KEY` が `sk_live_` で始まるか確認 |
| 性別が間違って登録された | スプレッドシートの性別欄が `female` / `male` になっているか確認 |
| 同一人物が二重処理された | 重複チェック済み（メールアドレスで検出）。ログに「重複検出」と表示される |
| 送信後にエラーが出た | `debug_screenshots/` にスクリーンショットが保存される |

---

## 横展開する場合

別のMVNOサービスで同様のシステムを構築する手順:

1. **jpmob_automator.py を差し替え**: 対象サイトのURL・セレクタ・フォーム構造に合わせる
2. **application_sheet.py のヘッダーを調整**: 収集する顧客情報に合わせる
3. **assignment_sheet.py のヘッダーを調整**: 記録する割り当て情報に合わせる
4. **gmail_sender.py のテンプレートを変更**: メール文面・件名を変更
5. **.env を設定**: 新しいサービスの認証情報を設定
6. **sheets_reader.py / main.py はそのまま使える**: 重複チェック・バリデーション等の安全機構は共通

### 横展開時に必ず確認すること

- [ ] 対象サイトのフォーム構造（モーダル? ページ遷移?）
- [ ] フォーム送信後の成功/失敗の判定方法
- [ ] 予約番号の発行タイミング（何分後に取得可能か）
- [ ] 性別・生年月日のフォーマット（サイトごとに異なる）
- [ ] 処理対象カードのフィルター条件（開通日・状態）

---

## 注意事項

- `.env` / `credentials.json` / `token.json` は **Git に含めない**
- `entered_cards.json` / `skipped_cards.json` は実行時キャッシュ（Git管理外）
- `debug_screenshots/` はエラー時のスクリーンショット（Git管理外）
- jpmob への入力は **8:00〜20:00** の間のみ実行される
- jpmob サイト: `console.jpmob.jp`
