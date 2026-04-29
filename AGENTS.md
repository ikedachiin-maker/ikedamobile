# ikedamobile SIM自動化システム — Codex 引き継ぎ資料

## プロジェクト概要

SIMカード申し込み処理を全自動化するシステム。
専用フォーム（Stripe決済付き）で受け付けた申し込みに対して、jpmob管理コンソール（console.jpmob.jp）への顧客情報入力・MNP予約番号取得・メール送信を自動で行う。

## ディレクトリ構成

```
jpmob-automation/
├── main.py                 # メイン処理（jpmob入力→予約番号→メール送信）
├── watcher.py              # 常駐監視（5分おきにスプレッドシートチェック、8:00〜20:00稼働）
├── jpmob_automator.py      # Selenium による jpmob 自動入力（★安全機構A/Bはここ）
├── sheets_reader.py        # Googleスプレッドシート読み書き
├── assignment_sheet.py     # 割り当て管理スプレッドシート
├── application_sheet.py    # 専用フォーム申し込み管理タブ
├── gmail_sender.py         # Gmail API でメール送信
├── retry_send.py           # 予約番号未発行分の再チェック（30分間隔）
├── reassign.py             # SIM再割り当てタスクの処理
├── webhook.py              # Stripe Webhook サーバー
├── reminder.py             # フォーム記入リマインダー送信
├── drive_uploader.py       # Google Drive アップロード
├── requirements.txt        # 依存ライブラリ
├── .env                    # 環境変数（Git管理外）
├── credentials.json        # Google OAuth認証情報（Git管理外）
├── token.json              # Google OAuthトークン（Git管理外）
└── venv/                   # Python 仮想環境
```

## 処理フロー

```
watcher.py（常駐、5分おき）
  ↓ 未処理レコード検知
main.py
  Step 1: スプレッドシートから未処理の申し込みを読み込み
  Step 2: jpmob に顧客情報を自動入力（安全機構A/B チェック後）
  Step 3: 割り当てシートに記録
  Step 4: 60分後に予約番号を取得
  Step 5: お客様にメールで予約番号を送信
```

## 開発環境

```bash
cd jpmob-automation
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 主な環境変数（.env）

| 変数名 | 説明 |
|---|---|
| `JPMOB_USERNAME` | jpmob ログインメールアドレス |
| `JPMOB_PASSWORD` | jpmob パスワード |
| `SPREADSHEET_ID` | Googleフォーム回答スプレッドシートID |
| `SHEET_NAME` | シート名（通常「フォームの回答 1」） |
| `GMAIL_SENDER` | 送信元Gmailアドレス |
| `STRIPE_SECRET_KEY` | Stripe シークレットキー |
| `JPMOB_OPEN_DATE_CUTOFF` | 処理対象とする開通日の下限（デフォルト: 2026-03-11） |

---

# ⚠️ 絶対に守るべきルール

## 安全機構A/B（データ破壊防止）

**別人のデータで既存の顧客情報を上書きしない** が最重要原則。
`jpmob_automator.py` の `_enter_user_info_impl()` に実装済み。
**このチェックを削除・弱体化する変更は絶対に行わないこと。**

### 安全機構A: モーダル内の既存フィールドを読み取ってスキップ

`_read_modal_existing_values(driver)` でモーダル内のフィールド（`last_name_kana`, `first_name_kana`, `last_name`, `first_name`, `birthday`）を読み取り、1つでも値が入っていればスキップ。`clear() + send_keys()` の前に必ず呼び出す。

※性別（sex）は判定対象外。jpmob の `<select>` はデフォルトが `male` で、未入力でも `male` を返すため誤判定の原因になる。

### 安全機構B: MNP予約番号が発行済みのカードをスキップ

`_get_existing_reservation_on_page(driver)` でカード詳細のMNP転出テーブルから予約番号を読み取り、値があればスキップ。モーダルを開く前に判定。

### 背景（2026-04-11 インシデント）

加村/文原のカードで、既存の顧客情報が上書きされる事故が発生。当時のコードは `el.clear() → el.send_keys()` で無条件上書きしていたため、jpmob が silent に拒否しても検知できなかった。この教訓から安全機構A/Bを追加。

## 22件の処理禁止カードID

以下のカードIDには **一切の自動処理を実行してはならない**（jpmob入力・割り当てシート更新・メール送信・予約番号取得すべて禁止）。

```
468556, 468557, 469022, 469023, 469027,
469028, 469029, 469030, 469031, 469062,
469063, 469064, 469065, 469066, 469067,
469068, 469069, 469070, 469071, 469072,
469073, 469074
```

**理由:** 2026-04-17、ローカルとGitHubのコード差分確認を怠り、安全機構A/Bが無い古いコードで main.py を実行。3/19の既存顧客データが上書きされた。16件は復元不可で破棄。全22件はオーナーが手動処理済み。

## コード変更時の必須チェック

- 安全機構A/Bに影響する変更は絶対にしない
- ファイル復元・同期時は `git hash-object` で全コアファイルのハッシュをGitHubと照合してから実行
- `.env`, `credentials.json`, `token.json` は機密情報、Git にコミットしない

---

# jpmob 管理コンソール 画面仕様

## 画面の流れ

1. ログイン → カード一覧（`iot_external_index`）で「開通済み」フィルター → カード詳細
2. カード詳細の「プラン」タブ内「カタカナ更新ボタン」→ モーダル表示
3. モーダル（`#update_mnp_user_info`）に6項目入力して送信
4. 同じ「プラン」タブ内「MNP転出」テーブルから予約番号・有効期限を取得

## ユーザー情報入力モーダルの6項目

| フィールド | HTML ID |
|---|---|
| 姓（フリガナ） | `last_name_kana` |
| 名（フリガナ） | `first_name_kana` |
| 姓（漢字） | `last_name` |
| 名（漢字） | `first_name` |
| 生年月日 | `birthday` |
| 性別 | `sex`（`<select>`、値は `male` / `female`） |

## jpmob 実機確認済み仕様

- MNP予約番号の有効期限が切れると、ステータスが「開通済み」に戻る（新規カードと区別不能）
- 複数セッション（マルチログイン）が許可されている（手動操作との併用可能）
- ユーザー情報入力済みでも「カタカナ更新ボタン」は表示され続ける（ボタン有無では判定不可）

---

# 自動運用

## launchd サービス（Mac mini 常駐）

| サービス | 用途 |
|---|---|
| `com.ikedamobile.watcher` | watcher.py 常駐監視 |
| `com.ikedamobile.webhook` | Stripe Webhook サーバー |

plist は `~/Library/LaunchAgents/` に配置。パスは `/Users/ikedayoshi/ikedamobile/jpmob-automation/`。

## Google OAuth 認証

本番モード移行済みでリフレッシュトークンは失効しない。`get_credentials()` がアクセストークンを自動更新。
スコープ: `spreadsheets`, `gmail.send`, `drive.file`

## GitHubリポジトリ

`ikedachiin-maker/ikedamobile`
