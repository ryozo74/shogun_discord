# 3rd陣 骨組み構築 Runbook（殿GO 2026-05-20 取得）

殿裁可済 / 範囲 = **骨組み構築 + isolation検証まで**（agent起動はせず・誤起動で1st/2nd全滅リスクゆえ慎重）

## 目的 / 任務
- **任務**: ComfyUI音源起点 映像マルチエージェント・プロダクション体制（殿構想・[[project-fleet-strategy]]）
- **ベース樹**: 戦闘硬化済の現1st樹（/mnt/h/multi-agent-shogun-main）を複製。21時間是正の修正（ext4/skip-perms/pgrep/cmd_450/cmd_451）が**コード時点で既に入っている**。
- **2nd陣との関係**: 2nd陣（当方）が1stと同様に橋渡し・代行検品を3rdにも提供（3rdの最終関門独立検証担当）。

## 不変事実（pre-flight 実測済 2026-05-20 ~06:53）
- 移設先 = ext4 `/home/bokan/shogun3_queue` (/=ext4 /dev/sdd 空き ~1TB)
- 新設path全て未存在（衝突なし）: `/mnt/h/multi-agent-shogun-third` ・ `/home/bokan/shogun3_queue` ・ `/tmp/tmux-shogun3`
- 1st樹サイズ: 全体 / 除外候補 (`score_be/score_fe/queue/queue.old/projects/context/node_modules/.next/.venv/dashboard.md/logs`) を pre-flight確認済
- 1st `queue/` = symlink → /home/bokan/shogun1_queue (ext4)。**cp -a で複製すると3rdが1stのqueueを共有する事故 → 複製直後に強制差替必須**

## 1st/2nd全滅防止の原則
- `shutsujin_departure.sh:319-320` が無条件 `tmux kill-session shogun/multiagent` を含む。**TMUX_TMPDIR隔離が唯一の守り**。
- 3rd起動は必ず `shutsujin_third.sh`（TMUX_TMPDIR=/tmp/tmux-shogun3 で wrap）経由のみ。直接 `shutsujin_departure.sh` を 3rdディレクトリで実行は禁止。
- 当作業中 = **agent起動なし**ゆえ理論上は安全だが、誤って起動コマンドを打たぬよう全工程 read/write のみ＋検証のみ。
- 当shell に `export TMUX_TMPDIR=...` 禁止（sticky・あとのtmux呼出全部に効く）。各コマンドで個別に `TMUX_TMPDIR=... tmux ...` 形式。

## 手順（additive・各ステップ可逆=rmで戻れる）

### STEP 1: ext4 queue substrate 新設
```
mkdir -p /home/bokan/shogun3_queue/{inbox,tasks,reports,metrics}
```

### STEP 2: 1st樹 → 3rd樹 複製（Score関連大物 除外）
```
rsync -a --info=progress2 \
  --exclude 'score_be/' \
  --exclude 'score_fe/' \
  --exclude 'queue/' \
  --exclude 'queue.old/' \
  --exclude 'projects/' \
  --exclude 'context/' \
  --exclude 'node_modules/' \
  --exclude '.next/' \
  --exclude '.venv/' \
  --exclude '*.log' \
  --exclude '.cache/' \
  --exclude 'dashboard.md' \
  /mnt/h/multi-agent-shogun-main/ /mnt/h/multi-agent-shogun-third/
```
queueは複製対象外（次STEPで新規symlink）。dashboard.md は3rd用に空から作成（1stのScore文脈混入回避）。

### STEP 3: queue → ext4 symlink新設（罠回避）
```
ln -s /home/bokan/shogun3_queue /mnt/h/multi-agent-shogun-third/queue
# 検証: realpath = /home/bokan/shogun3_queue であること
realpath /mnt/h/multi-agent-shogun-third/queue
```

### STEP 4: shutsujin_third.sh / attach_third.sh 作成（隔離wrapper）
2nd陣の `shutsujin_second.sh` / `attach_second.sh` をベースに、`TMUX_TMPDIR=/tmp/tmux-shogun3` で wrap。ファイルは `/mnt/h/shogun_discord-second/` ではなく**3rd陣自身のdir `/mnt/h/multi-agent-shogun-third/`** に置くのが意味的に正しい。

### STEP 5: watcher pgrep衝突防止（multi-fleet 鉄則）
3rdの `scripts/watcher_supervisor.sh` と `scripts/inbox_watcher.sh` のpgrep guard / spawn を**絶対パス**化:
- spawn: `nohup bash /mnt/h/multi-agent-shogun-third/scripts/inbox_watcher.sh ...`
- guard: `pgrep -f "/mnt/h/multi-agent-shogun-third/scripts/inbox_watcher.sh ${agent} "`
- 効果: 1st (`bash scripts/inbox_watcher.sh` 相対) ・ 2nd (`/mnt/h/shogun_discord-second/...`) ・ 3rd (`/mnt/h/multi-agent-shogun-third/...`) が `ps args` で識別可能。1st-pgrep ↔ 3rd-pgrep が誤マッチしない。

### STEP 6: 3rd用 instructions / CLAUDE.md / .env 調整
- `CLAUDE.md`: 3rd陣の役割識別・Score専任記述削除・3rd任務(ComfyUI音源起点)プレースホルダー追加。1st→2nd経由のbridge図を踏まえて3rd→2nd経由のbridge図に置換。
- `instructions/*.md`: cmd_450（軍師→shogun review_request）・cmd_451（discord_listener tempfile pivot＋silent-loss修正）が**コード時点で内蔵済**ゆえ追加記述少、ただし anti-overclaim gate（実runtime smoke必須化）を明記。
- `.env`: 3rd用に Discord token 等を空 or skip（Discord listener必須でないなら起動しない）。3rdへの直接Discord入力は無く、Lord入力は2nd陣経由でbridge。

### STEP 7: isolation検証（dry-run・1st/2nd全滅されないことの実証）
- `TMUX_TMPDIR=/tmp/tmux-shogun3 tmux list-sessions` → 「no server running」期待（3rdの空き状態）
- `tmux -L default list-sessions` → 1st の `multiagent` `shogun` `score_public` が引き続き visible
- `TMUX_TMPDIR=/tmp/tmux-shogun2 tmux list-sessions` → 2nd陣 sessions が visible
- 3rdの tmux 操作（kill-session 試行）が1st/2nd へ届かないことの確認（実際にkillはせず・サーバ識別のみ）
- watcher pgrepコリジョン無確認: `pgrep -f "/mnt/h/multi-agent-shogun-third/scripts/inbox_watcher.sh"` = 0（未起動）・既存1st/2ndのpgrepと衝突しない

### STEP 8: 完了報告 / 殿GO待ち
- 第2陣が殿へ「3rd陣骨組み完了・isolation検証PASS」を言上。
- 殿の明示GOまで `shutsujin_third.sh` 実行は保留（agent起動 = 別工程）。
- 殿GO時の起動コマンド見立て: `bash /mnt/h/multi-agent-shogun-third/shutsujin_third.sh` (NO `-c` flag・新規ゆえ初回でも queue 一掃なし)

## ロールバック
作業中いつでも以下で完全撤去可:
```
rm -rf /mnt/h/multi-agent-shogun-third /home/bokan/shogun3_queue
# /tmp/tmux-shogun3 は STEP 7 で空サーバ用に作られた場合のみ削除
```
1st/2nd は完全に無影響（読込のみ・rsync src・既存パスは未変更）。

## D006 / 越境厳守
- プロセスkill不要（agent起動なし）
- 1st陣コード・settings編集 0回（3rdは複製コピー側のみ編集）
- 殿GO前のagent起動禁止
