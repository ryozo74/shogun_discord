#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
# fleet_env.sh — 艦隊専用 tmux ソケットの単一定義（殿御下命 2026-07-30）
# ───────────────────────────────────────────────────────────────────────────────
# 1st/2nd/3rd の各艦隊は同名の tmux session (shogun / multiagent) を使う。
# 同一ソケット上に同居すると
#   (a) 後発艦隊の kill-session が他艦隊のペインを皆殺しにする
#   (b) 他艦隊の inbox_watcher の nudge / escalation の /clear が
#       こちらのエージェントを叩き、全文脈再読込でトークンを焼く
# ゆえに本艦隊は専用ソケットに隔離する。
#
# 既に環境に TMUX_TMPDIR があれば（＝ペイン内や出陣スクリプト経由）それを尊重し、
# 素のシェルから道具を叩かれた時だけ既定値を補う。
#
# 使い方（tmux を叩く全スクリプトの冒頭で）:
#   source "$(dirname "${BASH_SOURCE[0]}")/../lib/fleet_env.sh"
# ═══════════════════════════════════════════════════════════════════════════════

export TMUX_TMPDIR="${TMUX_TMPDIR:-/tmp/tmux-fleet-main}"
[ -d "$TMUX_TMPDIR" ] || { mkdir -p "$TMUX_TMPDIR" && chmod 700 "$TMUX_TMPDIR"; }
