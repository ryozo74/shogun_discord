# 設計ノート: famicom-fleet-board

## 1. アーキテクチャ

### 2-Tier ステータス検出
プロセス活動と filesystem 活動を併用し、両方をフォールバック関係で組み合わせる:

```
detect_agent_state(fleet, agent):
    # Tier-1: filesystem mtime (低コスト・古いと不正確)
    mtimes = [task.yaml, inbox.yaml] の max
    if mtime_age < 300s: state = work
    elif < 1800s: state = idle (status:work宣言なら work)
    else: state = idle
    if status:work かつ mtime > 2h: state = freeze

    # Tier-2: tmux pane CPU 増分 (高精度・最優先で上書き)
    if fleet tmux server alive:
        pane_pid = tmux display-message #{pane_pid}
        claude_pid = pgrep -P pane_pid (comm=claude のもの)
        cur_cpu = /proc/claude_pid/stat → utime+stime
        if prev_cpu 記録あり: delta = cur - prev
        active = delta >= max(0.2, elapsed * 0.03)  # 3% CPU 平均
        if active: state = work (filesystem判定に勝つ)
```

### Fleet 構成

| 陣 | デフォルトroot | tmux socket | 担当例 |
|---|---|---|---|
| 1st | `/mnt/h/multi-agent-shogun-main` | default (`/tmp/tmux-$UID/default`) | Score 専任 |
| 2nd | `/mnt/h/shogun_discord-second` | `/tmp/tmux-shogun2/tmux-$UID/default` | Discord 窓口 + 橋渡し |
| 3rd | `/mnt/h/multi-agent-shogun-third` | `/tmp/tmux-shogun3/tmux-$UID/default` | 別プロジェクト |

各陣の queue 構造:
```
<fleet-root>/queue/
├── tasks/<agent>.yaml       # 各 agent の現タスク
└── inbox/<agent>.yaml       # 各 agent への inbox
```

### Agent → tmux pane mapping

```python
AGENT_PANE = {
    'shogun':    'shogun:main.0',
    'karo':      'multiagent:agents.0',
    'gunshi':    'multiagent:agents.8',
    'ashigaru1': 'multiagent:agents.1',  ... 'ashigaru7': 'multiagent:agents.7',
}
```

## 2. 描画 (Pillow)

### キャンバス: 480×360px (NES風アスペクト)

### レイヤー (背面→前面):
1. 空グラデ (#203AA8 → #547CFC)
2. 雲 (装飾)
3. 地面 (茶色ストライプ)
4. 主城 (中央後方)
   - 石垣ベース (台形勾配・武者返し)
   - 石ブロック模様 (千鳥配置)
   - 大屋根 (反り曲線・両端跳ね上げ)
   - 漆喰壁 + 連子窓 (縦縞窓)
   - 破風 (中央三角装飾)
   - 中段
   - 上段 + 高欄 (廻縁)
   - 華頭窓 (上層中央)
   - 上段屋根
   - 鯱 (金色・対)
   - 旗 (赤・金家紋)
5. エージェント sprite (16×16 → 2x scale = 32×32)
   - 上段: 将軍 (中央前・赤鎧金兜) / 家老 (左・青衣) / 軍師 (右・紫衣)
   - 下段: 足軽1-7 (横並び・茶鎧笠)
6. 各 sprite の状態 halo (sprite外枠 2px)
7. 各 sprite 下の役名ラベル (将軍/家老/...) + 状態テキスト (作業中/待機/...)
8. 状態アイコン (頭上フキダシ + ZZZ アニメ)
9. ヘッダー (陣名 + 時刻) + フッター (集計 + 凡例)

### アニメ (3 frames・各 420ms・loop):
- idle: Z → ZZ → ZZZ (フキダシ + 上下揺れ)
- work: ⚒ → ⚔ → ⚒ (ハンマー→剣→ハンマー)
- freeze: ! → !! → !!! (左右震動)
- offline: アイコン非表示

## 3. Discord 投稿

### POST (初回) / PATCH (2回目以降)
- `POST /channels/{cid}/messages` で multipart 投稿 + payload_json
- `PATCH /channels/{cid}/messages/{msg_id}` + `attachments: []` で edit-in-place
- 失敗時 (404/403) は新規 POST に fallback

### state.yaml (msg ID 永続化)
```yaml
1st_msg_id: '...'
2nd_msg_id: '...'
3rd_msg_id: '...'
```
daemon 停止 → 再起動でも同 message を edit 継続 (チャネル散らからない)。

## 4. Token・rate limit 配慮

### Discord API rate limit
- per-channel: ~50 req/min (PATCH)
- daemon の interval=30秒 × 3 channel = 6 req/min ＝十分余裕

### 帯域
- GIF 1個 ≈ 25KB × 3 channel × 2 req/min ≈ 300KB/min (微小)

## 5. Phase 2 分散型のメリット

| 観点 | 集中型 | 分散型 |
|---|---|---|
| **耐障害性** | 集約daemon落ちると全停止 | 各陣 daemon は独立 |
| **bot 識別** | 全channel 同bot名義 | 各 channel に陣固有 bot |
| **管理**   | 1 daemon | 3 daemon (3個管理) |
| **設定** | 単一 channels.yaml | 各陣に分離 |

`--config/--env/--state/--log` flag で同コードを再利用可。

## 6. 既知の制約

- fleet root は現在 hardcoded (`FLEETS` dict)。将来 config化検討
- 「Lord 側 Claude Code session」(tmux外住人) は検出対象外。あくまで pane 常駐 fleet session の活動度を表示
- tmux server が動いていない陣 (3rd 起動前) は全 agent offline 表示
- queue.yaml の schema は `task: { task_id, status, ... }` ネスト前提。flat schema は別途対応要

## 7. 教訓ログ

### 2026-05-20 開発時の盲点
- **rsync --exclude 'queue/'** が symlink を意図せず複製 → 3rd陣で 1st queue 共有事故 (検証stepで即捕捉・ln -sfn で訂正)
- **PIL default font 日本語非対応** → MS Gothic (`/mnt/c/Windows/Fonts/msgothic.ttc`) を明示指定
- **tmux `#{pane_activity}` 未サポート** → `#{pane_pid}` 経由で /proc/<pid>/stat の CPU 累計時間 sample 比較に変更
- **「Lord と対話する Claude Code session」と「fleet常駐 sonnet session」は別 process** → ボード上の 2nd-shogun=待機 表示は正しい (pane常駐 session が静止)
