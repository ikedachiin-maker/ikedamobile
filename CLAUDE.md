# ikedamobile SIM自動化システム

## 概要

SIMカード申し込みの処理を自動化するシステム。
専用フォーム（Stripe決済付き）で受け付けた申し込みに対して、jpmob管理コンソールへの顧客情報入力・MNP予約番号取得・メール送信を全自動で行う。

## jpmob 管理コンソール 画面構造

スクリーンショットで確認した画面構造を記録。jpmob側の仕様変更時はここを更新すること。

### 画面の流れ

1. ログイン → カード一覧（`iot_external_index`）で「開通済み」フィルター → カード詳細
2. カード詳細の「プラン」タブ内に「カタカナ更新ボタン」がある → クリックでモーダル表示
3. モーダル（`#update_mnp_user_info`）に6項目入力して送信
4. 同じカード詳細の「プラン」タブ内「MNP転出」テーブルから予約番号・有効期限を取得

### ユーザー情報入力モーダルの6項目

| フィールド | HTML ID |
|---|---|
| 姓（フリガナ） | `last_name_kana` |
| 名（フリガナ） | `first_name_kana` |
| 姓（漢字） | `last_name` |
| 名（漢字） | `first_name` |
| 生年月日 | `birthday` |
| 性別 | `sex`（`<select>`、値は `male` / `female`） |

### jpmob の実機確認済み仕様

- **MNP予約番号の有効期限が切れると、ステータスが「MNP転出中」ではなく「開通済み」に戻る**
  → 有効期限切れカードが新規カードと区別できなくなるため、割り当てシートの予約番号列を再処理禁止の判定基準としている（`get_card_ids_with_reservation()`）
  → 電話番号 8015150572 で確認済み（2026年4月時点）

- **複数セッション（マルチログイン）が許可されている**
  → システム稼働中に手動でjpmobを操作しても、セッションが切断されない
  → PC・スマホ同時ログインで確認済み。システムと手動操作の併用が可能

### 処理対象の絞り込み条件

**発送日（開通日）が 2026年3月11日以降のカードのみ処理対象。**
環境変数 `JPMOB_OPEN_DATE_CUTOFF` で変更可能。

## 自動運用

### launchd による常時稼働（macOS）

`watcher.py` をlaunchdに登録すると、クラッシュ時の自動再起動・Mac再起動後の自動起動が有効になる。

```bash
# 登録（初回のみ）
cp com.ikedamobile.watcher.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.ikedamobile.watcher.plist

# 停止
launchctl unload ~/Library/LaunchAgents/com.ikedamobile.watcher.plist
```

ログ出力先：`watcher.log`（通常）、`watcher_error.log`（エラー）

### Google OAuth 認証について

本番モード（Google Cloud Console でアプリ公開済み）ではリフレッシュトークンが失効しないため、手動再認証は不要。アクセストークン期限切れ時は `get_credentials()` が自動で再取得する。

※テストモード時はリフレッシュトークンが7日で失効し手動再認証が必要だった。本番モード移行済み。

## 注意事項

- `.env`, `credentials.json`, `token.json` は機密情報のため Git 管理外
- `entered_cards.json`, `skipped_cards.json` は実行時キャッシュ（Git管理外）
- `debug_screenshots/` はエラー時のスクリーンショット（Git管理外）
