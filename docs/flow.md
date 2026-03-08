# ikedamobile 自動化システム 全体フロー

---

## フロー①：お客様が決済した直後（リアルタイム）

```
お客様が Stripe で決済
        ↓
Stripe が webhook.py に通知（/webhook）
        ↓
Googleフォームの URL をお客様にメール送信
        ↓
お客様がフォームに情報を記入・送信
```

---

## フロー②：フォーム送信後（リアルタイム）

```
お客様がGoogleフォームを送信
        ↓
Google Apps Script が起動
        ↓
webhook.py に通知（/form-trigger）
        ↓
main.py をバックグラウンドで起動
```

---

## フロー③：main.py の処理（8:00〜20:00のみ）

```
Googleスプレッドシートから申込データを読み込み
        ↓
jpmob（console.jpmob.jp）に顧客情報を自動入力
        ↓
割り当て情報を管理スプレッドシートに記録
        ↓
約1時間待機
        ↓
jpmob から予約番号・有効期限を取得
        ↓
管理スプレッドシートを更新
        ↓
お客様に予約番号等をメール送信
```

---

## フロー④：毎日9:00（cron）

```
reminder.py が起動
        ↓
フォームをまだ送信していないお客様をチェック
        ↓
リマインダーメールを送信
```

---

## 起動が必要なもの

| 何 | いつ | 方法 |
|---|---|---|
| webhook.py + Cloudflare Tunnel | Mac起動時（現在は手動） | `bash start_server.sh` |
| main.py | フォーム送信時に自動起動 | webhook経由 |
| reminder.py | 毎日9:00 | cron |

> **現在の課題：** Mac再起動のたびに `start_server.sh` を手動実行し、Google Apps ScriptのURLを更新する必要がある。
