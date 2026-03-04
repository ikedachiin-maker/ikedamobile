# jpmob-automation

ikedamobile の SIM カード申し込み処理を自動化するツール。

---

## 全体ワークフロー

```
【Stripe決済の場合】
1. お客様にStripe決済リンクを送る（またはLPを案内）
2. お客様が決済（メールアドレス自動収集）
3. python reminder.py を実行
   → 支払い済みのお客様にGoogleフォームURLをメール送信（自動）
   → 24時間後・48時間後にフォーム未記入ならリマインダー送信（自動）
4. お客様がGoogleフォームに記入
5. python main.py を実行
   → jpmobに顧客情報を自動入力 → 予約番号取得 → メール送信（自動）

【銀行振込の場合】
1. お客様に振込先情報を送る（LPまたは直接連絡）
2. お客様が振り込む
3. 入金確認（手動）
4. お客様にGoogleフォームURLを手動でメール送信
5. お客様がGoogleフォームに記入
6. python main.py を実行（自動）
```

**Mac mini で常時起動 → cron で定期実行が推奨。**

---

## ファイル構成

```
jpmob-automation/
├── main.py              # メイン処理（jpmob入力→予約番号→メール送信）
├── reminder.py          # フォーム記入リマインダー送信
├── jpmob_automator.py   # Selenium による jpmob 自動入力
├── sheets_reader.py     # Googleスプレッドシート読み込み・更新
├── gmail_sender.py      # Gmail API でメール送信
├── assignment_sheet.py  # 割り当て管理スプレッドシート
├── mark_all_processed.py # 既存レコードを一括「処理済み」にするユーティリティ
├── requirements.txt     # 依存ライブラリ
├── .env                 # 環境変数（GitHubには上げない！）
├── .env.example         # .env のテンプレート
├── credentials.json     # Google OAuth認証情報（GitHubには上げない！）
└── token.json           # Google OAuthトークン（GitHubには上げない！）

lp/
└── index.html           # 申し込みLP（ブラウザで開くだけで使える）
```

---

## Mac mini セットアップ手順

### 1. Python インストール確認

```bash
python3 --version   # 3.10以上であること
```

入っていない場合は https://www.python.org からインストール。

### 2. このリポジトリをクローン

```bash
git clone https://github.com/[あなたのユーザー名]/jpmob-automation.git
cd jpmob-automation
```

### 3. 仮想環境を作成・有効化

```bash
python3 -m venv venv
source venv/bin/activate
```

### 4. ライブラリをインストール

```bash
pip install -r requirements.txt
```

### 5. .env ファイルを作成

`.env.example` を参考に `.env` を作成する（GitHubには上がっていないので手動で作る）。

```bash
cp .env.example .env
```

以下の項目を埋める：

```env
JPMOB_USERNAME=ikedachiin@gmail.com
JPMOB_PASSWORD=（jpmobのパスワード）

SPREADSHEET_ID=1hrzI53VjeL5JW4O-LkofHj9GcukkhJf9SPyhkQ85GL0
SHEET_NAME=フォームの回答 1
ASSIGNMENT_SPREADSHEET_ID=（初回実行時に自動生成される）

GMAIL_SENDER=ikedachiin@gmail.com
GMAIL_SUBJECT=【ikedamobile】SIM情報のご連絡
GMAIL_EMAIL_COLUMN=メールアドレス

SEND_DELAY_SECONDS=3600
JPMOB_DEFAULT_SEX=male
STATUS_COLUMN=予約番号案内

STRIPE_SECRET_KEY=（StripeダッシュボードのAPIシークレットキー）
GOOGLE_FORM_URL=（GoogleフォームのURL）
REMINDER_HOURS_1=24
REMINDER_HOURS_2=48
```

### 6. Google 認証ファイルを配置

以下の2ファイルは機密情報のためGitHubに含まれていない。
**元のPCから Mac mini にコピーして配置する。**

- `credentials.json` → Google Cloud Console からダウンロードしたOAuthクライアントID
- `token.json` → 初回 `python main.py` 実行時にブラウザ認証して自動生成される

**コピー方法（元PCで実行）：**
```
場所: C:\Users\ysfm0664\OneDrive\Desktop\ikedamobile\jpmob-automation\credentials.json
```
USBやAirDropで Mac mini の `jpmob-automation/` フォルダに配置。

### 7. Chrome / ChromeDriver 確認

Selenium が Chrome を使うので Chrome がインストールされていること。
ChromeDriver は `webdriver-manager` が自動でインストールするので手動対応不要。

### 8. 動作テスト

```bash
cd jpmob-automation
source venv/bin/activate
python main.py
```

---

## Mac mini で cron 定期実行（推奨）

### cron を設定する

```bash
crontab -e
```

以下を追記（毎日9時にリマインダー、毎日10時にメイン処理を実行する例）：

```cron
# 毎日 9:00 にリマインダーチェック（フォーム未記入者へのメール）
0 9 * * * /Users/[ユーザー名]/jpmob-automation/venv/bin/python /Users/[ユーザー名]/jpmob-automation/reminder.py >> /Users/[ユーザー名]/jpmob-automation/reminder.log 2>&1

# 毎日 10:00 に jpmob 自動入力・メール送信
0 10 * * * /Users/[ユーザー名]/jpmob-automation/venv/bin/python /Users/[ユーザー名]/jpmob-automation/main.py >> /Users/[ユーザー名]/jpmob-automation/main.log 2>&1
```

> `[ユーザー名]` は Mac mini のユーザー名に置き換える（`whoami` で確認）。

---

## Stripe API キーの取得方法

1. [Stripe Dashboard](https://dashboard.stripe.com) にログイン
2. 左下「開発者」→「API キー」
3. 「シークレットキー」を `.env` の `STRIPE_SECRET_KEY=` に貼る

---

## Google Cloud / Gmail API の設定（初回のみ）

1. [Google Cloud Console](https://console.cloud.google.com) を開く
2. プロジェクト: **jpmob-automation**（既存）
3. APIとサービス → 認証情報 → OAuth 2.0 クライアントID をダウンロード → `credentials.json` として保存
4. 初回 `python main.py` 実行時にブラウザが開くので Google アカウントでログイン
5. `token.json` が自動生成される

---

## Google フォームの列名（現在の設定）

スプレッドシートの列名は以下に対応している（jpmob の入力フォームと一致）：

| Googleフォームの列名 | 用途 |
|---|---|
| 姓（漢字） | 名字（漢字） |
| 名（漢字） | 名前（漢字） |
| 姓（フリガナ） | 名字（カタカナ） |
| 名（フリガナ） | 名前（カタカナ） |
| 生年月日 | 生年月日（YYYY-MM-DD形式） |
| 性別 | 男性 or 女性 |
| メールアドレス | メール送信先 |
| 申込回線数 | SIM枚数（デフォルト1） |
| 予約番号案内 | 処理済みフラグ（TRUEで処理済み） |

---

## よくある操作

### 新規申し込みを処理する
```bash
python main.py
```

### フォーム記入リマインダーを送る
```bash
python reminder.py
```

### 既存の全レコードを処理済みにする（初回セットアップ時）
```bash
python mark_all_processed.py
```

---

## LP（申し込みページ）

`lp/index.html` をブラウザで開くと申し込みページが表示される。
GitHub Pages などで公開すればURLとして使える。
