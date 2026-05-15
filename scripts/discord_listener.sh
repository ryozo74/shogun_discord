#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# Discord Command Listener
# Polls Discord channel for Lord's messages, writes to discord_inbox.yaml,
# wakes shogun. REST API polling (no WebSocket/Gateway needed).
# ═══════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INBOX="$SCRIPT_DIR/queue/discord_inbox.yaml"
STATE_FILE="$SCRIPT_DIR/queue/discord_listener_state.txt"
LOCKFILE="${INBOX}.lock"
POLL_INTERVAL=3  # seconds between polls

# Load .env
set -a
[ -f "$SCRIPT_DIR/.env" ] && source "$SCRIPT_DIR/.env"
set +a

TOKEN="${DISCORD_BOT_TOKEN:-}"
CHANNEL_ID="${DISCORD_CMD_CHANNEL_ID:-}"
LORD_ID="${DISCORD_USER_ID:-}"

if [ -z "$TOKEN" ] || [ -z "$CHANNEL_ID" ] || [ -z "$LORD_ID" ]; then
    echo "[discord_listener] Required env vars missing: DISCORD_BOT_TOKEN, DISCORD_CMD_CHANNEL_ID, DISCORD_USER_ID" >&2
    exit 1
fi

# Initialize inbox if not exists
if [ ! -f "$INBOX" ]; then
    echo "inbox: []" > "$INBOX"
fi

# Load last processed message ID
LAST_MSG_ID=""
if [ -f "$STATE_FILE" ]; then
    LAST_MSG_ID=$(cat "$STATE_FILE" | tr -d '[:space:]')
fi

# JSON field extractor (python3)
# Reads API response from $DISCORD_API_RESPONSE env var to avoid stdin/heredoc conflict.
parse_messages() {
    DISCORD_API_RESPONSE="$1" python3 - "$LORD_ID" <<'PY'
import os, sys, json

lord_id = sys.argv[1]
raw = os.environ.get("DISCORD_API_RESPONSE", "")
try:
    data = json.loads(raw)
except Exception:
    sys.exit(0)
if not isinstance(data, list):
    sys.exit(0)
for msg in reversed(data):  # reversed: oldest first
    author = msg.get("author", {})
    if author.get("id") != lord_id:
        continue
    msg_id = msg.get("id", "")
    ts = msg.get("timestamp", "")
    content = msg.get("content", "").strip()
    if content:
        print(json.dumps({'id': msg_id, 'ts': ts, 'content': content}))
PY
}

append_discord_inbox() {
    local msg_id="$1"
    local ts="$2"
    local msg="$3"

    (
        if command -v flock &>/dev/null; then
            flock -w 5 200 || exit 1
        else
            _ld="${LOCKFILE}.d"; _i=0
            while ! mkdir "$_ld" 2>/dev/null; do sleep 0.1; _i=$((_i+1)); [ $_i -ge 50 ] && exit 1; done
            trap "rmdir '$_ld' 2>/dev/null" EXIT
        fi
        DISCORD_INBOX_PATH="$INBOX" \
        MSG_ID="$msg_id" \
        MSG_TS="$ts" \
        MSG_TEXT="$msg" \
        python3 - << 'PY'
import os, sys, yaml, tempfile

path = os.environ["DISCORD_INBOX_PATH"]
entry = {
    "id": os.environ.get("MSG_ID", ""),
    "timestamp": os.environ.get("MSG_TS", ""),
    "message": os.environ.get("MSG_TEXT", ""),
    "status": "pending",
}

data = {}
if os.path.exists(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f)
        if isinstance(loaded, dict):
            data = loaded
    except Exception:
        data = {}

items = data.get("inbox")
if not isinstance(items, list):
    items = []
items.append(entry)
data["inbox"] = items

tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
try:
    with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    os.replace(tmp_path, path)
except Exception as e:
    print(f"[discord_listener] write failed: {e}", file=sys.stderr)
    sys.exit(1)
PY
    ) 200>"$LOCKFILE"
}

echo "[$(date)] discord_listener started — channel: ${CHANNEL_ID} — lord: ${LORD_ID}" >&2

while true; do
    # Build URL with after parameter
    URL="https://discord.com/api/v10/channels/${CHANNEL_ID}/messages?limit=100"
    if [ -n "$LAST_MSG_ID" ]; then
        URL="${URL}&after=${LAST_MSG_ID}"
    fi

    # Fetch messages
    RESPONSE=$(curl -s \
        -H "Authorization: Bot ${TOKEN}" \
        -H "Content-Type: application/json" \
        "$URL" 2>/dev/null)

    if [ -z "$RESPONSE" ] || [ "$RESPONSE" = "[]" ]; then
        sleep "$POLL_INTERVAL"
        continue
    fi

    # Check for API errors
    if echo "$RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if isinstance(d,list) else 1)" 2>/dev/null; then
        # Process messages (filtered by LORD_ID)
        while IFS= read -r json_line; do
            [ -z "$json_line" ] && continue
            msg_id=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d['id'])" "$json_line")
            ts=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d['ts'])" "$json_line")
            content=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d['content'])" "$json_line")
            [ -z "$msg_id" ] && continue
            echo "[$(date)] Received from Lord: ${content:0:50}" >&2

            if ! append_discord_inbox "$msg_id" "$ts" "$content"; then
                echo "[$(date)] WARNING: failed to write discord_inbox" >&2
                continue
            fi

            # Update last_msg_id
            LAST_MSG_ID="$msg_id"
            echo "$LAST_MSG_ID" > "$STATE_FILE"

            # Wake shogun
            bash "$SCRIPT_DIR/scripts/inbox_write.sh" shogun \
                "Discordから新しいメッセージ受信。queue/discord_inbox.yaml を確認し処理せよ。" \
                discord_received discord_listener
        done < <(parse_messages "$RESPONSE")

        # Update LAST_MSG_ID even if no messages matched (to skip bot/other messages)
        LATEST_ID=$(echo "$RESPONSE" | python3 -c "
import sys,json
msgs = json.load(sys.stdin)
if isinstance(msgs, list) and msgs:
    print(msgs[0]['id'])  # Discord returns newest first
" 2>/dev/null)
        if [ -n "$LATEST_ID" ] && { [ -z "$LAST_MSG_ID" ] || [ "$LATEST_ID" \> "$LAST_MSG_ID" ]; }; then
            LAST_MSG_ID="$LATEST_ID"
            echo "$LAST_MSG_ID" > "$STATE_FILE"
        fi
    else
        echo "[$(date)] Discord API error: $(echo "$RESPONSE" | head -c 200)" >&2
        sleep 10  # Back off on error
    fi

    sleep "$POLL_INTERVAL"
done
