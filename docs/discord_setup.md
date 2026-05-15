# Discord Bot Integration Setup

## Overview

2チャネル構成:
- **命令チャネル** (DISCORD_CMD_CHANNEL_ID): 殿↔将軍双方向
- **ダッシュボードチャネル** (DISCORD_DASHBOARD_CHANNEL_ID): 将軍→殿片方向

ntfy との並走: ntfy.sh は残置。Discord連携は追加チャネル。

## Prerequisites

- Python 3.x (`.venv/bin/python3` or system python3)
- curl
- Discord アカウント

## Step 1: Discord Bot 作成

1. Discord Developer Portal (https://discord.com/developers/applications) にアクセス
2. "New Application" → アプリ名入力 (例: "Shogun Bot")
3. 左メニュー "Bot" → "Add Bot"
4. Bot Token をコピー（後で .env に設定）
5. **Privileged Gateway Intents**: "MESSAGE CONTENT INTENT" を有効化（Developer Portal → Bot → Privileged Gateway Intents）
6. **Permissions**: "Send Messages" + "Read Message History" のみ有効化（Administrator は付与しない）

## Step 2: 必要なIDの収集

Discord の設定 > 詳細設定 > 開発者モードを有効化してから:

| 変数名 | 取得方法 |
|--------|---------|
| DISCORD_BOT_TOKEN | Developer Portal → Bot → Token（Step 1でコピー済） |
| DISCORD_USER_ID | Discord上で自分のアカウントを右クリック → "Copy User ID" |
| DISCORD_CMD_CHANNEL_ID | 命令チャネルを右クリック → "Copy Channel ID" |
| DISCORD_DASHBOARD_CHANNEL_ID | ダッシュボードチャネルを右クリック → "Copy Channel ID" |

## Step 3: .env 設定

プロジェクトルートの `.env` に設定（`.env.example` を参照）:

```
DISCORD_BOT_TOKEN=your_actual_bot_token_here
DISCORD_USER_ID=your_discord_user_id
DISCORD_CMD_CHANNEL_ID=your_command_channel_id
DISCORD_DASHBOARD_CHANNEL_ID=your_dashboard_channel_id
```

⚠️ `.env` は `.gitignore` 済。**絶対に git commit するな**。

## Step 4: Bot をサーバに招待

Bot招待URL生成:
```
https://discord.com/api/oauth2/authorize?client_id=YOUR_APPLICATION_ID&permissions=2048&scope=bot
```
- `YOUR_APPLICATION_ID` は Developer Portal → General Information → Application ID
- permissions=2048 = "Send Messages" のみ

1. URLをブラウザで開く
2. サーバを選択 → 認証
3. BotがサーバのメンバーリストにBOTバッジで表示されればOK

## Step 5: 動作確認

### 送信テスト
```bash
bash scripts/discord.sh "Test from Shogun 🏯"
```
命令チャネルにメッセージが届けばOK。

### Listenerテスト
```bash
# フォアグラウンドで起動してログを確認
bash scripts/discord_listener.sh
```
別ウィンドウで命令チャネルに `テスト` と投稿 → `[timestamp] Received from Lord: テスト` が出ればOK。

### ダッシュボード同期テスト
```bash
bash scripts/discord_dashboard_sync.sh
```
ダッシュボードチャネルにdashboard.mdの内容が投稿されればOK。
2回実行すると同じメッセージが編集される（新規投稿でない）ことを確認。

## Step 6: Listener バックグラウンド起動

### tmux セッションで起動（推奨）
```bash
# Shogun セッションの空きペインで:
bash scripts/discord_listener.sh
```

### バックグラウンド起動
```bash
nohup bash scripts/discord_listener.sh &>/dev/null &
echo $! > /tmp/discord_listener.pid
```

### shutsujin_departure.sh への組み込み（オプション）
将来的に `shutsujin_departure.sh` で自動起動させる場合は、ntfy_listener と同じパターンで追加。

## 会話履歴の閲覧

殿の発言（inbox）と将軍の返信（outbox）を時系列マージして PC コンソールで確認できる。

```bash
# 最新30件の双方向会話を時系列表示（120字超は ...省略）
bash scripts/discord_conversation.sh

# 最新N件を指定
bash scripts/discord_conversation.sh -n 50

# 全文表示（省略なし）
bash scripts/discord_conversation.sh -v

# 組み合わせ
bash scripts/discord_conversation.sh -n 20 -v
```

出力例:
```
[2026-05-14T19:32:21 JST] 殿: A案『...』
[2026-05-14T19:33:05 JST] 将軍: 畏まりました殿。U-01 A案 拝承仕った。
[2026-05-14T23:24:41 JST] 殿: discordでの会話もPCのコンソール内で確認したい
```

**仕組み**:
- `queue/discord_inbox.yaml`: `scripts/discord_listener.sh` が殿の発言を追記
- `queue/discord_outbox.yaml`: `scripts/discord.sh` が将軍の送信成功時に追記（cmd_438 で追加）
- 両者を timestamp で昇順ソートしてマージ表示

**セキュリティ**: `discord.sh` は `DISCORD_BOT_TOKEN` を outbox に**書き込まない**。channel_id（数値ID）と content（メッセージ本文）と timestamp のみが保存される。

## ダッシュボード同期: 2000文字制限の対処

dashboard.md は2000文字を超える可能性があるため、以下の方針を採用:
- **実装方針**: 冒頭1800文字を抜粋 + "...(省略。全文は dashboard.md を参照)" を末尾付加
- **Edit Message**: 毎回削除して投稿し直すのではなく、同一メッセージを PATCH で更新
- **状態ファイル**: `queue/discord_dashboard_msg_id.txt` にメッセージIDを保存

将来的な拡張として embed 分割も可能だが、現時点はシンプルな抜粋方式を採用。

## セキュリティ注意事項

- DISCORD_BOT_TOKEN は `.env` のみで管理
- `.env` を `git add` しないこと（`.gitignore` 済だが `git add -f` も禁止）
- Bot に Administrator 権限は付与しない
- DISCORD_USER_ID フィルタにより殿以外の発言は全て無視される
- Privileged Intent (MESSAGE CONTENT INTENT) が必要な理由: チャネルメッセージの本文を読むため

## Troubleshooting

| 症状 | 原因 | 対処 |
|------|------|------|
| discord.sh が何も送らない | TOKEN/CHANNEL_ID未設定 | .env を確認 |
| listener がメッセージを拾わない | DISCORD_USER_ID 不一致 | Developer Modeで自分のIDを再確認 |
| 403 Forbidden | Bot がチャネルに参加していない | Bot をサーバ招待してチャネルの閲覧権限を付与 |
| 401 Unauthorized | TOKEN が間違い or 失効 | Developer Portal でトークンをリセット |
| Message Content Intent | Bot がメッセージ本文を読めない | Developer Portal で MESSAGE CONTENT INTENT を有効化 |

## 協働運用（Multi-Shogun）

複数の将軍 Bot を同一の Discord コマンドチャンネルで協働させる機能です。

### 動作モード

| `DISCORD_MULTI_SHOGUN` | 動作 |
|------------------------|------|
| 未設定 / `false`（デフォルト） | 従来動作：殿の全発言を処理 |
| `true` | ルーティングモード：@メンション対象のみ処理 |

### メンション方式

- **特定将軍への指示**: `@将軍のBot名` でメンション → その将軍のみ実行
- **全将軍への指示**: `@everyone` → 全将軍が実行
- **無印（メンションなし）**: ルーティングモード時は無視。将軍の stderr に1回ログ出力。
  `@将軍 か @everyone を付与されたし` というメッセージが表示されます。

### 設定手順

1. **将軍ごとに別個の Discord Bot アプリを作成**してください（Bot トークンが別になる）
   - Bot が別 id を返すため、殿は返信 Bot 名で将軍甲乙を識別できます
   - レート制限も独立するため、並列実行に安全です

2. 各将軍の `.env` に以下を追加:
   ```env
   DISCORD_MULTI_SHOGUN=true
   # DISCORD_BOT_USER_ID は自動取得されます。失敗時のみ手動設定してください。
   # DISCORD_BOT_USER_ID=your_bot_user_id
   # 任意: @role でも全将軍同時指示を受け付ける場合
   # DISCORD_SHOGUN_ROLE_ID=your_role_id
   ```

3. `queue/` ディレクトリは **将軍ごとに独立したリポジトリに配置**してください
   - 同一 `queue/` の共有は禁止です。共有すると inbox の競合が発生します。
   - 各将軍は自身の `queue/inbox/{agent}.yaml` のみを監視します。

### 運用上の注意

- **将軍 Bot への返信は明示的な @メンションを推奨**
  Discord では将軍 Bot の発言に返信すると、allowed_mentions 設定によっては
  Bot が `mentions` に自動追加される場合があります。意図しない実行を避けるため、
  殿の発言は常に `@将軍名` や `@everyone` を明示してください。

- `@everyone` は Discord サーバー設定により権限が制限される場合があります。
  代替として `DISCORD_SHOGUN_ROLE_ID` に将軍ロールの id を設定すると、
  @ロールメンションでも全将軍同時指示が可能です。
