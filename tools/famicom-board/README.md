# famicom-fleet-board

複数の **multi-agent AI 艦隊** のステータスを、Discord channel 上に **ファミコン風ドット絵 GIF** で可視化する自動更新ボード。

![sample](docs/sample_image_placeholder.png)
*第1陣 (Score専任) ・第2陣 (Discord窓口) ・第3陣 (任意) のそれぞれの将軍・家老・軍師・足軽7体 (計10名) を 1枚のドット絵に描画。各キャラに状態halo (緑=作業中 / 灰=待機 / 赤=凍結 / 黒=未起動)・頭上に黒フキダシで Z→ZZ→ZZZ のアニメ。30秒毎に edit-in-place で Discord channel pinned message を更新。*

## 特徴

- **Token消費ゼロ**：純Python daemon・LLM API には触れず・ファイルシステム + tmux + Discord API のみ
- **日本天守閣風背景**：石垣武者返し勾配・反り屋根3層・破風・金鯱・金家紋旗
- **動的状態判定**：tmux pane 内の claude プロセスの CPU 使用量増分を観測 (filesystem mtime もfallback)
- **集中型 / 分散型 切替対応**：`--fleet` ・ `--config` / `--env` / `--state` / `--log` の path override flag で 1台daemon集中 or 各陣個別 daemon どちらにも対応

## 仕組み

```
        ┌─────────────────┐
1st陣 → queue/tasks/ ┐    │
                    │    │
2nd陣 → queue/tasks/ │ → famicom_board.py (Pillow ドット絵生成)
                    │    │       ↓
3rd陣 → queue/tasks/ ┘    │   GIF (3 frames アニメ)
                          │       ↓
1st/2nd/3rd tmux pane → CPU使用観測 (claude pid → /proc)
                          │       ↓
                          │   famicom_board_post.py
                          │       ↓
                          └→ Discord API (bot token・edit-in-place)
                                   ↓
                          Discord channel #1st/2nd/3rd-fleet-status
```

## 必要なもの

- Python 3.10+
- Discord Bot Token (1〜3個・集中型なら 1つで OK)
- 各艦隊の queue/tasks/<agent>.yaml が読める filesystem 上で稼働 (cross-fleet 同一PC前提)
- tmux サーバ (各艦隊用に別 socket・例: 1st=default / 2nd=/tmp/tmux-shogun2 等)

## セットアップ

### 1. venv + 依存導入

```bash
python3 -m venv /home/your_user/.venvs/famicom_board
/home/your_user/.venvs/famicom_board/bin/pip install -r requirements.txt
```

### 2. Discord Bot 用意 (集中型なら1つ)

- https://discord.com/developers/applications で新規 application → Bot 作成
- Bot Token 取得 (Reset Token 1回・初回のみ表示)
- 必要権限:`Send Messages` `Attach Files` `Read Message History`
- Bot を該当 channel に招待 (server invite URL or channel メンバー追加)

### 3. channel ID 取得

- Discord 開発者モード ON (ユーザー設定→詳細設定)
- 各 channel 右クリック → 「IDをコピー」 (19桁数字)

### 4. config と .env を用意 (実ファイルは .gitignore で除外)

```bash
cp config/famicom_board_channels.yaml.example config/famicom_board_channels.yaml
# 編集して channel ID を記入

# .env を作成 (またはコピー元から)
cat > .env <<EOF
DISCORD_BOT_TOKEN=あなたの_bot_token
EOF
```

### 5. fleet root path の調整

現在 `scripts/famicom_board.py` の `FLEETS` dict に陣の root path が hardcoded されています:

```python
FLEETS = {
    '1st': '/mnt/h/multi-agent-shogun-main',
    '2nd': '/mnt/h/shogun_discord-second',
    '3rd': '/mnt/h/multi-agent-shogun-third',
}
```

利用環境に合わせて編集。各 fleet には `queue/tasks/<agent>.yaml` と `queue/inbox/<agent>.yaml` が必要。 tmux socket dirも `FLEET_TMUX` で定義。

将来 (Phase 2 仕上げ) には config化予定。

## 起動

### 集中型 (1 daemon で3陣全部)

```bash
/home/your_user/.venvs/famicom_board/bin/python3 scripts/famicom_board_post.py --interval 30
```

### 分散型 (各陣で個別 daemon・推奨)

各陣の root で:

```bash
# 1st 陣 daemon
nohup /home/your_user/.venvs/famicom_board/bin/python3 \
  /path/to/famicom-fleet-board/scripts/famicom_board_post.py \
  --interval 30 \
  --fleet 1st \
  --config /1st-fleet-root/config/famicom_board_channels.yaml \
  --env /1st-fleet-root/.env \
  --state /1st-fleet-root/var/famicom_board_state.yaml \
  --log /1st-fleet-root/logs/famicom_board.log \
  > /tmp/famicom_board_1st_daemon.log 2>&1 &
```

### dry-run (Discord 投稿せず・GIF だけ生成)

```bash
/home/your_user/.venvs/famicom_board/bin/python3 scripts/famicom_board_post.py --dry-run
# 出力: /tmp/famicom_board_{1st,2nd,3rd}.gif
```

## CLI 引数

| 引数 | 既定 | 説明 |
|---|---|---|
| `--interval N` | 30 | 更新間隔(秒)・Discord rate limit 安全範囲 |
| `--once` | - | 1回だけ実行して終了 (cron 用) |
| `--dry-run` | - | GIF 生成のみ・Discord 投稿せず |
| `--fleet 1st\|2nd\|3rd\|all` | all | 対象陣を限定 (分散型向け) |
| `--config PATH` | (内蔵) | channel_map.yaml path override |
| `--env PATH` | (内蔵) | .env path override |
| `--state PATH` | (内蔵) | state.yaml path override |
| `--log PATH` | (内蔵) | log file path override |

## ステータス検出ロジック

| 状態 | 判定条件 |
|---|---|
| **作業中** (work / 緑) | tmux pane の claude プロセス CPU 累計が interval 内で 3% 以上増 |
| | あるいは task.yaml / inbox.yaml の mtime が 5分以内 |
| **待機** (idle / 灰) | mtime 5-30分・status: work 明示なし |
| **凍結** (freeze / 赤) | status: work かつ mtime > 2h (作業宣言で長時間動かず) |
| **未起動** (offline / 黒) | task/inbox file 不在 (陣未起動) |

詳細は [`docs/design.md`](docs/design.md) 参照。

## License

shogun_discord 本体と同じ MIT — repo root の [`LICENSE`](../../LICENSE) 参照。
本 tools の追加 author: **studiobokan** (Co-authored by Claude)。

## 開発履歴・教訓

- 2026-05-20: v1 (集中型 + 1st-fleet 分散化) 完遂・日本天守閣＋ZZZ強調採用
- 教訓: 「Lord 側 Claude Code session」と「pane常駐 fleet session」は別 process。tmux pane_pid 経由検出はあくまで **fleet常駐session** の活動度を捉える
- 教訓: rsync `--exclude 'queue/'` は symlink を意図せず複製してしまう罠あり (3rd陣構築時に検知)
