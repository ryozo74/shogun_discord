#!/usr/bin/env bash
# 🏯 2nd将軍 専用アタッチヘルパ
# ───────────────────────────────────────────────────────────────────────────
# 2nd将軍フリート(隔離tmuxサーバ)へ安全にアタッチする。
# 手作業で TMUX_TMPDIR を打たずに済むようにするための薄いラッパ。
#
# 使い方:
#   bash attach_second.sh            # shogun 本陣へ
#   bash attach_second.sh multiagent # 家老+足軽+軍師 へ
#   bash attach_second.sh ls         # 2nd隔離サーバのセッション一覧
#
# 注意: これは 2nd 専用。1st へは素の `tmux attach -t shogun` を使う
#       (TMUX_TMPDIR を設定しないこと)。
# ───────────────────────────────────────────────────────────────────────────
set -u
export TMUX_TMPDIR="/tmp/tmux-shogun2"

if [ ! -d "$TMUX_TMPDIR" ]; then
    echo "【注意】$TMUX_TMPDIR が無い = 2nd将軍はまだ出陣していません。" >&2
    echo "        先に: bash shutsujin_second.sh" >&2
    exit 1
fi

target="${1:-shogun}"
case "$target" in
    ls|list)   exec tmux ls ;;
    shogun)    exec tmux attach -t shogun ;;
    multiagent|agents) exec tmux attach -t multiagent ;;
    *)         exec tmux attach -t "$target" ;;
esac
