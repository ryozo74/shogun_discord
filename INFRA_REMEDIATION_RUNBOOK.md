# 第1陣 基盤是正 Runbook（queue→ext4 移設 ＋ 家老allowlist）

殿裁可済 / GO方式 = **某がクリーン確認 → 殿明示GO → 実行**（自動実行せぬ）

## 目的（根因）
1. `/mnt/h`=9p(drvfs) は flock/原子性/整合性なし → queue YAML 固着・陳腐化・偽記録の温床（cmd_447で2度の偽将軍PASS=記録偽造の根）。
2. 家老が許可promptで凍結（自inbox読込・整合追記YAML等の良性操作にallowlist無し）。

## 不変事実（scoping実測済）
- 移設先: **ext4 `/home/bokan/shogun1_queue`**（`/`=ext4 /dev/sdd 空き~1TB）。/tmp=tmpfs(揮発)は不可。
- `inbox_write.sh` 等は `$SCRIPT_DIR/queue/...` 相対解決・絶対パスのハードコード無し → **symlink差替でゼロ改修・全参照透過**。
- **Score本番 :8100 は queue/ を使わない**（.env と CalendarAPI のみ）→ **移設中も無停止**。本作業は“エージェント協調層の保守窓”。
- watcher_supervisor 現在 **2プロセス**（重複）→ 窓で1本に整理。

## 実行GOの前提（全て満たすまでGOせぬ／某が実測で裏取り）
- [ ] 第1陣が偽 将軍検品PASS 記録を撤回・dashboard是正済
- [ ] 家老が dashboard/queue を**ext4移設前提で永続化済**（最新が確実に書けている）
- [ ] in-flight 足軽サブタスク無し（**ashigaru3/ashigaru6 の assigned/in_progress を done/idle へ reconcile** ＝某の前回実測の食い違い解消）
- [ ] cmd_447 Phase5 未着手（保留継続）・全エージェント idle/Cooked
- [ ] 某が runbook 最終化＋殿が明示GO

## 手順（graceful・ロールバック可）

### STEP 0  バックアップ（停止前）
```
rsync -a --delete /mnt/h/multi-agent-shogun-main/queue/ /home/bokan/shogun1_queue/   # 初回同期(稼働中・後で最終差分)
```

### STEP 1  graceful quiesce（第1陣）
- 第1陣: 進行サブタスク完了 or 安全park → dashboard/queue flush → 「quiesce完了」を第2陣へ一報。

### STEP 2  協調層 停止（プロセス停止は D006 ゆえ殿=人間が実施、エージェントは kill せぬ）
- 殿/運用者が停止: watcher_supervisor ×2、第1陣 inbox_watcher 群（agentCLI/tmuxは存置でよい・協調層のみ）。
- **Score :8100(pid現行) は停止しない**（無停止）。
- 第2陣が「協調層停止・queue書込み静止」を実測確認。

### STEP 3  移設（symlink swap・原本保全）
```
rsync -a --delete /mnt/h/multi-agent-shogun-main/queue/ /home/bokan/shogun1_queue/   # 最終差分同期
mv /mnt/h/multi-agent-shogun-main/queue /mnt/h/multi-agent-shogun-main/queue.old      # 原本保全(削除せぬ=即ロールバック路)
ln -s /home/bokan/shogun1_queue /mnt/h/multi-agent-shogun-main/queue                  # 透過symlink
```

### STEP 4  家老 allowlist 適用
- 第1陣 karo の settings.json（要prep実測でパス確定）に、実証済良性のみ allowlist:
  - `Read` の `queue/inbox/karo.yaml`（自inbox読込＝Inbox Protocol）
  - プロジェクト内 `queue/**` への整合追記YAML書込（全置換でない）
- 破壊/不明/プロジェクト外 は従来どおりプロンプト→将軍/殿エスカレ（盲目承認禁止の則は維持）。可逆（settings編集）。

### STEP 5  再起動（協調層）
- watcher_supervisor を **1本だけ**起動（symlink越しに ext4 queue を監視）→ inbox_watcher 群 自動再生成。
- 第1陣エージェント復帰（必要なら inbox nudge）。

### STEP 6  スモークテスト（第2陣 独立・記録信じぬ）
- [ ] `inbox_write.sh` 往復: shogun2へtest投函→ext4実体に反映→flock競合無し→read:true処理可
- [ ] 並行書込→即読: A書込直後にB読取で**陳腐化せず即見える**（元バグの回帰確認）
- [ ] inotifywait/watcher が ext4 symlink先の変更を検知しnudge
- [ ] 本番 :8100 独立 per-user: taoka→user_id32 / kuromaru→46 / 不在→403（無停止維持の確認）
- [ ] watcher_supervisor が**1本のみ**・重複再発なし
- [ ] 第1陣エージェントが queue Read/Write 正常・凍結なし

### STEP 7  完了 or ロールバック
- 全スモークPASS → 第2陣が殿へ完了言上。`queue.old` は数日 観察後に運用者撤去。
- いずれか FAIL → 即ロールバック:
```
（協調層停止）→ rm /mnt/h/multi-agent-shogun-main/queue ; mv queue.old queue →（再起動）
```
  ＝既知の(緩いが動く)/mnt状態へ復帰。ダウンは協調層のみ・Score無停止。

## 役割境界
- プロセス停止/起動 = 殿(人間)主導（D006: エージェントkill不可）。第2陣は実測・symlink/rsync・スモーク・言上を担当。
- 第1陣 = quiesce・allowlist対象settings提示・復帰後の自己診断。
- GO = 前提全充足を第2陣が実測裏取り → 殿明示GO。某は独断実行せぬ。
