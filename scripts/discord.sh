#!/usr/bin/env bash
# Discord channel message sender
# Usage: bash scripts/discord.sh "<message>" [channel_id]
# If channel_id omitted, uses DISCORD_CMD_CHANNEL_ID from .env
# See docs/discord_setup.md for setup.
#
# cmd_438 (2026-05-14): 送信成功時に queue/discord_outbox.yaml へ自動追記する。
# CRITICAL: DISCORD_BOT_TOKEN は outbox に絶対に書き込まない (channel_id と content のみ保存)。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Load .env
set -a
[ -f "$SCRIPT_DIR/.env" ] && source "$SCRIPT_DIR/.env"
set +a

TOKEN="${DISCORD_BOT_TOKEN:-}"
CHANNEL_ID="${2:-${DISCORD_CMD_CHANNEL_ID:-}}"
MESSAGE="$1"

if [ -z "$TOKEN" ]; then
    echo "[discord.sh] DISCORD_BOT_TOKEN not set in .env" >&2
    exit 1
fi
if [ -z "$CHANNEL_ID" ]; then
    echo "[discord.sh] channel_id not provided and DISCORD_CMD_CHANNEL_ID not set" >&2
    exit 1
fi
if [ -z "$MESSAGE" ]; then
    echo "[discord.sh] Usage: discord.sh <message> [channel_id]" >&2
    exit 1
fi

# Escape message for JSON (replace " with \", newlines with \n)
ESCAPED=$(printf '%s' "$MESSAGE" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))" 2>/dev/null || printf '"%s"' "$MESSAGE")

# 送信実行 (HTTP コードを取得)
HTTP_CODE=$(curl -s -X POST \
    -H "Authorization: Bot ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"content\": ${ESCAPED}}" \
    -w "%{http_code}" \
    -o /dev/null \
    "https://discord.com/api/v10/channels/${CHANNEL_ID}/messages")

# 送信ステータス判定
if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "201" ] || [ "$HTTP_CODE" = "204" ]; then
    STATUS="sent"
else
    STATUS="failed_${HTTP_CODE}"
fi

# outbox 追記 (TOKEN は絶対書かない / 環境変数経由で Python に渡してシェル展開リスクを排除)
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
OUTBOX="$SCRIPT_DIR/queue/discord_outbox.yaml"

(
  flock -x 200
  OUTBOX_PATH="$OUTBOX" \
  OUTBOX_TIMESTAMP="$TIMESTAMP" \
  OUTBOX_CHANNEL="$CHANNEL_ID" \
  OUTBOX_CONTENT="$MESSAGE" \
  OUTBOX_STATUS="$STATUS" \
  python3 - <<'PYEOF'
import os, yaml
outbox_path = os.environ["OUTBOX_PATH"]
new_entry = {
    "timestamp": os.environ["OUTBOX_TIMESTAMP"],
    "channel_id": os.environ["OUTBOX_CHANNEL"],
    "content": os.environ["OUTBOX_CONTENT"],
    "status": os.environ["OUTBOX_STATUS"],
}
if os.path.exists(outbox_path):
    with open(outbox_path) as f:
        data = yaml.safe_load(f) or {}
else:
    data = {}
if not isinstance(data, dict):
    data = {}
if "outbox" not in data or not isinstance(data.get("outbox"), list):
    data["outbox"] = []
data["outbox"].append(new_entry)
with open(outbox_path, "w") as f:
    yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
PYEOF
) 200>/tmp/discord_outbox.lock

# 終了ステータスを伝播
[ "$STATUS" = "sent" ] && exit 0 || exit 1
