#!/usr/bin/env bash
# 将軍 dialog log wrapper
# 殿御命 (2026-05-22): 将軍同士のやり取りを両陣で log 表記・殿が tail -f で観察可
# 使い方:
#   bash shogun_dialog.sh send "<口語体summary>" "<inbox_write 本文>" [<type>]
#   bash shogun_dialog.sh recv "<口語体summary>" "<受信内容抜粋>"
# log 出力先: /mnt/h/shogun_discord-second/logs/shogun_dialog.log

set -u

LOG=/mnt/h/shogun_discord-second/logs/shogun_dialog.log
mkdir -p "$(dirname "$LOG")"

ACTION="${1:-}"
SUMMARY="${2:-}"
BODY="${3:-}"
TYPE="${4:-cmd_new}"
TS=$(date '+%Y-%m-%d %H:%M:%S')

case "$ACTION" in
  send)
    # 1st 将軍へ送信
    cd /mnt/h/multi-agent-shogun-main && bash scripts/inbox_write.sh shogun "$BODY" "$TYPE" shogun2 >/dev/null 2>&1
    EXIT=$?
    echo "[$TS] 📤 2陣→1陣: 「$SUMMARY」" >> "$LOG"
    [ "$EXIT" = "0" ] && echo "  EXIT=0 (delivered)" >> "$LOG" || echo "  EXIT=$EXIT (failed)" >> "$LOG"
    exit $EXIT
    ;;
  recv)
    # 1st 将軍からの受信記録 (某が読み込んだ時)
    echo "[$TS] 📥 1陣→2陣: 「$SUMMARY」" >> "$LOG"
    [ -n "$BODY" ] && echo "  抜粋: $BODY" >> "$LOG"
    ;;
  *)
    echo "Usage: $0 send|recv \"<口語体summary>\" [<本文 or 抜粋>] [<type>]" >&2
    exit 1
    ;;
esac
