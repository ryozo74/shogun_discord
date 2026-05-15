#!/usr/bin/env bash
# Discord dashboard sync — posts dashboard.md to DISCORD_DASHBOARD_CHANNEL_ID
# Uses Edit Message API to update a single persistent message.
# Run: bash scripts/discord_dashboard_sync.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DASHBOARD="$SCRIPT_DIR/dashboard.md"
MSG_ID_FILE="$SCRIPT_DIR/queue/discord_dashboard_msg_id.txt"

# Load .env
set -a
[ -f "$SCRIPT_DIR/.env" ] && source "$SCRIPT_DIR/.env"
set +a

TOKEN="${DISCORD_BOT_TOKEN:-}"
CHANNEL_ID="${DISCORD_DASHBOARD_CHANNEL_ID:-}"

if [ -z "$TOKEN" ] || [ -z "$CHANNEL_ID" ]; then
    echo "[discord_dashboard_sync] DISCORD_BOT_TOKEN or DISCORD_DASHBOARD_CHANNEL_ID not set" >&2
    exit 1
fi
if [ ! -f "$DASHBOARD" ]; then
    echo "[discord_dashboard_sync] dashboard.md not found" >&2
    exit 1
fi

# Read dashboard.md and truncate to 1800 chars
CONTENT=$(head -c 3600 "$DASHBOARD")
if [ ${#CONTENT} -gt 1800 ]; then
    CONTENT="${CONTENT:0:1800}"$'\n'"...(省略。全文は dashboard.md を参照)"
fi

# JSON-encode content
PAYLOAD=$(python3 -c "import sys,json; print(json.dumps({'content': sys.stdin.read()}))" <<< "$CONTENT" 2>/dev/null)
if [ -z "$PAYLOAD" ]; then
    echo "[discord_dashboard_sync] Failed to encode JSON payload" >&2
    exit 1
fi

# Check if we have an existing message ID
if [ -f "$MSG_ID_FILE" ]; then
    MSG_ID=$(cat "$MSG_ID_FILE" | tr -d '[:space:]')
fi

if [ -n "$MSG_ID" ]; then
    # Edit existing message (PATCH)
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X PATCH \
        -H "Authorization: Bot ${TOKEN}" \
        -H "Content-Type: application/json" \
        -d "$PAYLOAD" \
        "https://discord.com/api/v10/channels/${CHANNEL_ID}/messages/${MSG_ID}")

    if [ "$HTTP_CODE" = "200" ]; then
        echo "[discord_dashboard_sync] Dashboard updated (msg_id: $MSG_ID)" >&2
        exit 0
    else
        echo "[discord_dashboard_sync] PATCH failed (HTTP $HTTP_CODE), will create new message" >&2
        rm -f "$MSG_ID_FILE"
        MSG_ID=""
    fi
fi

# Create new message (POST)
RESPONSE=$(curl -s -X POST \
    -H "Authorization: Bot ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" \
    "https://discord.com/api/v10/channels/${CHANNEL_ID}/messages")

NEW_ID=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
if [ -n "$NEW_ID" ]; then
    echo "$NEW_ID" > "$MSG_ID_FILE"
    echo "[discord_dashboard_sync] Dashboard posted (msg_id: $NEW_ID)" >&2
else
    echo "[discord_dashboard_sync] Failed to post: $RESPONSE" >&2
    exit 1
fi
