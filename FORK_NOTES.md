# Fork Notes — `manage-studiobokan/shogun_discord`

## 関係

```
upstream:  ryozo74/shogun_discord (public・OSS)
              │
              │ base commit: 1099b56 (cmd_442 Discord multi-shogun routing)
              ↓
this fork:  manage-studiobokan/shogun_discord
              │
              │ multi-fleet (1st / 2nd / 3rd) 共存運用 + audio2mov 連携 改造
              ↓
            本 fork は 2nd-fleet (Discord 窓口・橋渡し) として運用中
```

## 主な改造内容 (upstream に存在しない 第2陣固有 file 10 件)

### multi-fleet 共存運用 (1 台の PC で 1st / 2nd / 3rd を独立起動)

| file | 役割 |
|---|---|
| `attach_second.sh` | 2nd-fleet 用 tmux attach wrapper (`TMUX_TMPDIR=/tmp/tmux-shogun2` 隔離) |
| `INFRA_REMEDIATION_RUNBOOK.md` | ext4 queue 移行・cmd_447/450/451 等の運用手順記録 |
| `THIRD_FLEET_BUILDOUT_RUNBOOK.md` | 3rd-fleet (ComfyUI 音源起点映像 multi-agent) 構築手順 |

### multi-fleet 通信

| file | 役割 |
|---|---|
| `scripts/shogun_dialog.sh` | 将軍同士 (1st⇄2nd⇄3rd) の対話を口語体で log + inbox_write の wrapper |
| `scripts/discord_pending_watcher.sh` (※whitelist 外・将来追加) | 60秒 polling の軽量 daemon・LLM 不要で Discord pending を検知 |

### famicom board (Discord channel 上の fleet status visualizer)

| file | 役割 |
|---|---|
| `scripts/famicom_board.py` | ファミコン風 GIF + 数字パネル (作業N/待機M/凍結X/未起動Y) を 3 fleet 別 Discord channel に edit-in-place 投稿する daemon |
| `scripts/famicom_board_post.py` | 上記 daemon のメインループ |
| `sample_1st.gif`, `sample_2nd.gif`, `sample_3rd.gif` | 3 fleet 用サンプル GIF |

**注**: upstream は 2026-05-20 に `tools/famicom-board/` 配下に同等機能を追加 (#1 PR・別 path・別実装)。本 fork は `scripts/` 直下に第2陣独自実装版を保持。

### Discord 自動応答 (現在停止中・残存)

| file | 役割 |
|---|---|
| `scripts/discord_autorespond.sh` | 旧来の tool-less `claude -p` persona bot (fabrication 過去で停止中・`queue/discord_autorespond.stop` で永続停止) |

## 設計哲学

### 1. fleet 独立性

- 1st-fleet: 既存 OSS (ryozo74/shogun_discord) + Score project 専任
- 2nd-fleet: 本 fork・Discord 窓口 + 1st⇄3rd 橋渡し
- 3rd-fleet: ComfyUI 音源起点 multi-agent 映像制作 project (audio2mov)

各 fleet は別 `TMUX_TMPDIR` で完全隔離・互いの `tmux kill-session` が他 fleet に届かない設計。

### 2. .gitignore whitelist 方式

upstream の `.gitignore` を踏襲: デフォルト全除外 → OSS 公開対象のみ `!` で許可。secret (`.env` / `JWT_SECRET` / queue state) は **commit 不可** が保証される。第2陣固有 file は `# ── 第2陣 (multi-fleet) 固有改造ファイル ──` セクションで明示的に whitelist 追加。

### 3. upstream との関係

- 本 fork は upstream の純粋な superset を目指さない (改造 path が異なる)
- famicom-board は upstream `tools/famicom-board/` と 本 fork `scripts/` で 重複実装
- 将来 upstream に rebase する場合は、famicom-board の path 統一が必要

## audio2mov 連携 (3rd-fleet)

本 fork の `THIRD_FLEET_BUILDOUT_RUNBOOK.md` は・別 dir (`/mnt/h/multi-agent-shogun-third/`) で稼働する 3rd-fleet (audio2mov project) の構築手順を記録。audio2mov 自体のソースは別 repo (ryozo74/audio2mov・private) で管理。

3rd-fleet との通信は本 fork の 2nd-fleet 経由:
- 殿 → Discord → 2nd-fleet listener → 2nd shogun → 3rd shogun (inbox_write)
- 3rd shogun → 2nd shogun (inbox_write) → 殿への報告

## License

upstream (ryozo74/shogun_discord) と同じ MIT (LICENSE 参照)。第2陣改造部分も同 license で公開。

## 連絡先

- 本 fork 管理: studiobokan (殿)
- upstream: ryozo74 (殿の元 account)
