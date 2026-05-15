#!/usr/bin/env bash
# Discord 双方向会話ビューア
# inbox (殿発言) + outbox (将軍返信) を時系列マージ表示する
#
# Usage:
#   bash scripts/discord_conversation.sh           # 最新30件 (120字超は ...省略)
#   bash scripts/discord_conversation.sh -n 50     # 最新50件
#   bash scripts/discord_conversation.sh -v        # 全文表示 (省略なし)
#   bash scripts/discord_conversation.sh -n 20 -v
#
# cmd_438 (2026-05-14): 殿御要望「Discord 会話を PC コンソールから時系列確認」に応答。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INBOX="$SCRIPT_DIR/queue/discord_inbox.yaml"
OUTBOX="$SCRIPT_DIR/queue/discord_outbox.yaml"
LIMIT=30
VERBOSE=0

while getopts ":n:v" opt; do
  case $opt in
    n) LIMIT="$OPTARG" ;;
    v) VERBOSE=1 ;;
    *) echo "Usage: $0 [-n N] [-v]" >&2; exit 1 ;;
  esac
done

if [ ! -f "$INBOX" ] && [ ! -f "$OUTBOX" ]; then
    echo "[discord_conversation.sh] inbox/outbox どちらも存在しない。" >&2
    exit 1
fi

CONV_INBOX="$INBOX" \
CONV_OUTBOX="$OUTBOX" \
CONV_LIMIT="$LIMIT" \
CONV_VERBOSE="$VERBOSE" \
python3 - <<'PYEOF'
import os, sys, yaml
from datetime import datetime, timezone, timedelta

inbox_path = os.environ["CONV_INBOX"]
outbox_path = os.environ["CONV_OUTBOX"]
limit = int(os.environ["CONV_LIMIT"])
verbose = os.environ["CONV_VERBOSE"] == "1"

events = []

# inbox (殿発言)
if os.path.exists(inbox_path):
    try:
        with open(inbox_path) as f:
            data = yaml.safe_load(f) or {}
        for e in (data.get("inbox") or []):
            events.append({
                "ts": e.get("timestamp", "") or "",
                "who": "殿",
                "content": e.get("message", "") or "",
                "status": e.get("status", "") or "",
            })
    except Exception as exc:
        print(f"[warn] inbox 読込失敗: {exc}", file=sys.stderr)

# outbox (将軍返信)
if os.path.exists(outbox_path):
    try:
        with open(outbox_path) as f:
            data = yaml.safe_load(f) or {}
        for e in (data.get("outbox") or []):
            events.append({
                "ts": e.get("timestamp", "") or "",
                "who": "将軍",
                "content": e.get("content", "") or "",
                "status": e.get("status", "sent") or "sent",
            })
    except Exception as exc:
        print(f"[warn] outbox 読込失敗: {exc}", file=sys.stderr)

def parse_ts(s):
    if not s:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        if s.endswith("Z"):
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)

events.sort(key=lambda e: parse_ts(e["ts"]))

# 最新 limit 件
events = events[-limit:] if limit > 0 else events

JST = timezone(timedelta(hours=9))

for e in events:
    dt = parse_ts(e["ts"])
    jst = dt.astimezone(JST)
    ts_str = jst.strftime("%Y-%m-%dT%H:%M:%S")

    content = e["content"]
    if not verbose and len(content) > 120:
        content = content[:117] + "..."
    content = content.replace("\n", " | ")

    # status が異常系 (failed_NNN) の場合のみ末尾表示
    status_suffix = ""
    if e["who"] == "将軍" and e["status"] and e["status"] != "sent":
        status_suffix = f"  ⚠️[{e['status']}]"

    print(f"[{ts_str} JST] {e['who']}: {content}{status_suffix}")
PYEOF
