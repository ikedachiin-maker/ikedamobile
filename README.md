# jpmob-automation

ikedamobile の SIM カード申し込み処理を自動化するツール。
専用申し込みフォーム（Stripe決済付き）からの申し込みを受け付け、jpmob への顧客情報入力・予約番号取得・メール送信を全自動で行う。

---

## 本番環境

| 項目 | 値 |
|------|-----|
| **サービスURL** | https://ikedamobile.com |
| **Railwayサービス** | web-production-1398a.up.railway.app |
| **ホスティング** | Railway（Hobby プラン $5/月） |
| **ドメイン** | Cloudflare Registrar（ikedamobile.com） |
| **Stripe Webhook** | https://ikedamobile.com/webhook |

### アーキテクチャ

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
      Mac mini（cron 定期実行）
      ・毎日 10:00 に main.py 実行
      ・jpmob への顧客情報入力
      ・予約番号取得 → お客様にメール送信
```

### Railway 設定

- **リポジトリ**: ikedachiin-maker/ikedamobile
- **Root Directory**: `/`（空欄・リポジトリルート）
- **Builder**: Nixpacks（railway.toml で設定）
- **起動コマンド**: `gunicorn --bind 0.0.0.0:$PORT --workers 1 --timeout 120 webhook:app`（Procfile）

### Railway 環境変数の更新方法

1. [Railway ダッシュボード](https://railway.app) にログイン
2. `independent-imagination` プロジェクト → `web` サービス
3. **Variables タブ** → **Raw Editor** で一括編集
4. 変更後は **Deploy** ボタンで再デプロイ

### Railway デプロイの注意点

- `GOOGLE_CREDENTIALS_JSON` / `GOOGLE_TOKEN_JSON` は JSON ファイルの中身をそのまま環境変数に設定
- Railway では `PORT` 環境変数が自動設定される（`WEBHOOK_PORT` は不使用）
- ファイルアップロードは **Google Drive** に保存（`drive_uploader.py`）
- `main.py` は Mac の cron で実行するため Railway には不要

---

## 全体ワークフロー

```
【専用フォーム（Stripe決済）の場合】
1. お客様が LP（lp/index.html）からプランを選択
2. 専用申し込みフォーム（lp/form.html）に個人情報・本人確認書類をアップロード
3. Stripe でカード決済
4. 申し込み情報がスプレッドシート「申し込み管理」タブに自動記録
5. main.py が自動起動
   → jpmob の開通済みSIMに顧客情報を入力（開通日フィルター・二重処理防止あり）
   → 約1時間後に予約番号を取得
   → お客様にメールで予約番号を送信

【銀行振込の場合】
1. お客様に振込先情報を送る（LPまたは直接連絡）
2. お客様が振り込む
3. 入金確認（手動）
4. お客様に Google フォーム URL を手動でメール送信
5. お客様が Google フォームに記入
6. main.py が自動起動（上記 5 と同様）
```

> **Mac を起動するだけで全自動で動作する。**（launchd による自動起動）

---

## ファイル構成

```
jpmob-automation/
├── main.py               # メイン処理（jpmob入力 → 予約番号取得 → メール送信）
├── webhook.py            # Flask サーバー（LP配信・フォームAPI・Stripe Webhook）
├── jpmob_automator.py    # Selenium による jpmob 自動入力（開通日フィルター付き）
├── sheets_reader.py      # Google スプレッドシート読み込み・更新
├── application_sheet.py  # 「申し込み管理」タブの管理（専用フォーム用）
├── assignment_sheet.py   # 「割り当て」タブの管理（カードID・予約番号の記録）
├── gmail_sender.py       # Gmail API でメール送信
├── reminder.py           # フォーム記入リマインダー送信
├── mark_all_processed.py # 既存レコードを一括「処理済み」にするユーティリティ
├── check_open_cards.py   # 開通済みカード調査スクリプト（運用管理用）
├── extract_2025_iccid.py # 特定期間のICCID抽出スクリプト（運用管理用）
├── drive_uploader.py     # Google Drive へのファイルアップロード（Railway 本番用）
├── Procfile              # Railway 起動コマンド（gunicorn）
├── railway.toml          # Railway ビルド設定（Nixpacks）
├── requirements.txt      # 依存ライブラリ
├── .env                  # 環境変数（Git 管理外・機密情報）
├── .env.example          # .env のテンプレート
├── credentials.json      # Google OAuth 認証情報（Git 管理外）
├── token.json            # Google OAuth トークン（Git 管理外・初回自動生成）
├── uploads/              # 本人確認書類のアップロード先（Git 管理外）
└── venv/                 # Python 仮想環境（Git 管理外）

lp/
├── index.html            # 申し込み LP
└── form.html             # 専用申し込みフォーム（Stripe Elements 統合）
```

---

## 処理対象カードのルール

### 開通日フィルター

`JPMOB_OPEN_DATE_CUTOFF`（デフォルト: `2026-03-13`）以降に開通したカードのみ処理する。
それより前に開通した既存カードは**自動処理の対象外**。

### スキップ条件（以下のいずれかに該当するカードは処理しない）

| 条件 | 理由 |
|------|------|
| 状態が「MNP転出中」「解約」「解約済み」 | すでに処理済みまたは解約された回線 |
| 開通日が `JPMOB_OPEN_DATE_CUTOFF` より前 | 自動処理対象外の既存カード |
| 「割り当て」タブに既登録の card_id | 二重処理防止 |

---

## セットアップ手順（初回）

### 1. Python・Chrome の確認

```bash
python3 --version   # 3.10 以上であること
# Chrome がインストールされていること（ChromeDriver は自動インストール）
```

### 2. リポジトリをクローン

```bash
git clone https://github.com/ikedachiin-maker/ikedamobile.git
cd ikedamobile/jpmob-automation
```

### 3. 仮想環境を作成・有効化

```bash
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
```

### 4. ライブラリをインストール

```bash
pip install -r requirements.txt
```

### 5. .env ファイルを作成

```bash
cp .env.example .env
```

`.env` を開いて以下の項目を設定する：

```env
# jpmob ログイン
JPMOB_USERNAME=ikedachiin@gmail.com
JPMOB_PASSWORD=（jpmob のパスワード）

# Google スプレッドシート
SPREADSHEET_ID=1hrzI53VjeL5JW4O-LkofHj9GcukkhJf9SPyhkQ85GL0
SHEET_NAME=フォームの回答 1

# Gmail 送信
GMAIL_SENDER=ikedachiin@gmail.com
GMAIL_SUBJECT=【ikedamobile】SIM情報のご連絡
GMAIL_EMAIL_COLUMN=メールアドレス

# Stripe
STRIPE_SECRET_KEY=sk_live_xxxxxxxxxxxxxxxx
STRIPE_PUBLISHABLE_KEY=pk_live_xxxxxxxxxxxxxxxx
STRIPE_WEBHOOK_SECRET=whsec_xxxxxxxxxxxxxxxx

# 動作設定
SEND_DELAY_SECONDS=3600           # jpmob 入力後の待機時間（秒）
JPMOB_OPEN_DATE_CUTOFF=2026-03-13 # この日以降に開通したカードのみ処理
JPMOB_DEFAULT_SEX=male
STATUS_COLUMN=予約番号案内

# Webhook サーバー
WEBHOOK_PORT=5000
FORM_TRIGGER_SECRET=（任意のランダム文字列）

# リマインダー
GOOGLE_FORM_URL=https://forms.gle/xxxxxxxx
REMINDER_HOURS_1=24
REMINDER_HOURS_2=48
```

### 6. Google 認証ファイルを配置

以下の2ファイルは機密情報のため Git に含まれていない。

| ファイル | 取得方法 |
|---------|---------|
| `credentials.json` | Google Cloud Console > 認証情報 > OAuth 2.0 クライアントID をダウンロード |
| `token.json` | 初回 `python main.py` 実行時にブラウザ認証で自動生成 |

```bash
# 別PCからコピーする場合（AirDrop または USB）
# 配置先: ~/ikedamobile/jpmob-automation/credentials.json
```

### 7. launchd 自動起動の設定（Mac）

```bash
launchctl load ~/Library/LaunchAgents/com.ikedamobile.webhook.plist
```

停止する場合：

```bash
launchctl unload ~/Library/LaunchAgents/com.ikedamobile.webhook.plist
```

### 8. 動作確認

```bash
# サーバーが起動しているか確認
curl http://localhost:5000/

# ログを確認
tail -f ~/ikedamobile/jpmob-automation/main.log
tail -f ~/ikedamobile/jpmob-automation/webhook.log
```

---

## cron 定期実行設定

```bash
crontab -e
```

以下を追記：

```cron
# 毎日 9:00 にリマインダーチェック（フォーム未記入者へのメール）
0 9 * * * /Users/ikedayoshi/ikedamobile/jpmob-automation/venv/bin/python /Users/ikedayoshi/ikedamobile/jpmob-automation/reminder.py >> /Users/ikedayoshi/ikedamobile/jpmob-automation/reminder.log 2>&1

# 毎日 10:00 に jpmob 自動入力・メール送信
0 10 * * * /Users/ikedayoshi/ikedamobile/jpmob-automation/venv/bin/python /Users/ikedayoshi/ikedamobile/jpmob-automation/main.py >> /Users/ikedayoshi/ikedamobile/jpmob-automation/main.log 2>&1
```

---

## スプレッドシート構成

| タブ名 | 用途 | 書き込み元 |
|--------|------|-----------|
| フォームの回答 1 | Google フォーム回答（銀行振込のお客様） | Google Forms 自動 |
| 申し込み管理 | 専用フォームからの申し込み（カード決済のお客様） | webhook.py |
| 割り当て | jpmob カードID・予約番号・送信状況の記録 | main.py |

### 「申し込み管理」タブの列

| 列名 | 内容 |
|------|------|
| タイムスタンプ | 申し込み日時 |
| 姓（漢字）/ 名（漢字） | 氏名 |
| 姓（フリガナ）/ 名（フリガナ） | フリガナ |
| 生年月日 / 性別 | 個人情報 |
| メールアドレス | 連絡先 |
| プラン | consul / online / general |
| 申込回線数 | 申し込み回線数 |
| 決済金額 | 実際の支払額（円） |
| 決済ID | Stripe PaymentIntent ID |
| 本人確認書類 | アップロードファイルのUUID |
| 予約番号案内 | 空=未処理 / TRUE=処理済み |

### 「割り当て」タブの列

| 列名 | 内容 |
|------|------|
| タイムスタンプ | 処理日時 |
| 顧客名 | 氏名（漢字） |
| メールアドレス | 連絡先 |
| SIM電話番号 | 割り当てたSIMの電話番号 |
| カードID | jpmob 内部ID |
| 入力日時 | jpmob 入力完了日時 |
| 予約番号 | jpmob が発行した予約番号 |
| 有効期限 | 予約番号の有効期限 |
| メール送信済み | 未送信 / 送信済み |

---

## 主な操作コマンド

```bash
cd ~/ikedamobile/jpmob-automation
source venv/bin/activate

# 新規申し込みを手動処理する（jpmob入力 → 予約番号取得 → メール送信）
python main.py

# フォーム記入リマインダーを手動送信
python reminder.py

# Webhook サーバーを手動起動（通常は launchd が自動起動）
python webhook.py

# 既存の全レコードを処理済みにする（初回セットアップ時のみ）
python mark_all_processed.py

# 開通済みカード一覧と開通日を調査する（運用管理用）
python check_open_cards.py

# 特定期間の開通カードの ICCID を抽出する（運用管理用）
python extract_2025_iccid.py
```

---

## Stripe 料金設定

| プラン | 単価（1回線あたり） |
|--------|------------------|
| consul（コンサル）| ¥3,000 |
| online（オンライン）| ¥3,300 |
| general（一般）| ¥3,600 |

> 申し込み回線数 × 単価が決済金額となる。

---

## Stripe API キーの確認・取得

1. [Stripe Dashboard](https://dashboard.stripe.com) にログイン
2. 左下「開発者」→「API キー」
3. シークレットキー → `.env` の `STRIPE_SECRET_KEY` に設定
4. 公開可能キー → `.env` の `STRIPE_PUBLISHABLE_KEY` に設定（フォームのJS用）
5. Webhook 署名シークレット → 「開発者」→「Webhook」→「署名シークレット」→ `.env` の `STRIPE_WEBHOOK_SECRET` に設定

---

## Google Cloud / Gmail API の設定（初回のみ）

1. [Google Cloud Console](https://console.cloud.google.com) を開く
2. プロジェクト: **jpmob-automation**（既存）
3. 「APIとサービス」→「認証情報」→「OAuth 2.0 クライアントID」をダウンロード
4. `credentials.json` として `jpmob-automation/` に保存
5. 初回 `python main.py` 実行時にブラウザが開く → Google アカウントでログイン
6. `token.json` が自動生成される（以降は不要）

---

## 開通日フィルターの変更方法

`.env` の `JPMOB_OPEN_DATE_CUTOFF` を変更するだけ：

```env
# 例: 2026年4月1日以降に開通したカードのみ処理する場合
JPMOB_OPEN_DATE_CUTOFF=2026-04-01
```

変更後は webhook サーバーを再起動：

```bash
launchctl unload ~/Library/LaunchAgents/com.ikedamobile.webhook.plist
launchctl load  ~/Library/LaunchAgents/com.ikedamobile.webhook.plist
```

---

## トラブルシューティング

### サーバーが起動しない

```bash
# プロセス確認
ps aux | grep webhook.py

# ログ確認
cat ~/ikedamobile/jpmob-automation/main.log
```

### jpmob にログインできない

`.env` の `JPMOB_USERNAME` / `JPMOB_PASSWORD` を確認。

### Google スプレッドシートに書き込めない

```bash
# token.json を削除して再認証
rm token.json
python main.py  # ブラウザで再ログイン
```

### Stripe 決済が通らない

`.env` の `STRIPE_SECRET_KEY` が `sk_live_` から始まる本番キーであることを確認。

---

## 注意事項

- `.env` / `credentials.json` / `token.json` は**絶対に Git にコミットしない**
- `uploads/` フォルダには本人確認書類が保存される（Git 管理外）
- Selenium は Chrome を使用するため、**Chrome がインストールされていること**
- jpmob への入力は **8:00〜20:00** の間のみ実行される（時間外は自動待機）
- 開通日フィルター（`JPMOB_OPEN_DATE_CUTOFF`）は `2026-03-11` がデフォルト

---

## 今後の課題

### Mac がスリープしていると cron が動かない問題

`main.py`（jpmob 自動入力）と `reminder.py`（リマインダー送信）は Mac の cron で毎日定時実行しているため、**その時間帯に Mac が起動・稼働していないと処理がスキップされる**。

Mac がスリープ中・電源オフの場合は当日の処理が行われない。

#### 対策案（優先度順）

| 方法 | 概要 | 難易度 |
|------|------|--------|
| **Mac の自動起動設定** | システム環境設定 → バッテリー → 「スケジュール」で毎日 9:50 に自動起動 | ★☆☆ |
| **Railway Cron サービス追加** | Railway に別サービスを追加し、`main.py` をクラウドで定時実行する。ただし Selenium（Chrome）が Railway では動作しないため、jpmob 入力部分の改修が必要 | ★★★ |
| **jpmob API 対応** | jpmob が API を提供している場合は Selenium を廃止しクラウド完結できる | ★★★ |

現状は **Mac の自動起動設定** が最も低コストな対策。

---

## 変更履歴

### 2026-03-11

- **本番公開**: `ikedamobile.com` にて LP・申し込みフォームが正常に表示されることを確認
- **Railway Root Directory 修正**: `jpmob-automation` → `/`（空欄）に変更。これによりビルド失敗が解消され展開成功
- **開通日フィルター変更**: `JPMOB_OPEN_DATE_CUTOFF` を `2026-03-13` → `2026-03-11` に変更（3月11日以降開通のSIMを処理対象に）
- **今後の課題追記**: Mac スリープ時に cron が動かない問題と対策案をREADMEに記載

### 次のアクション（予定）

- 3月13日: SIM到着後にテスト決済を実施し、予約番号発行までの全フローを確認
