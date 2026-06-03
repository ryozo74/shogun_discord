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

# Multi-shogun: resolve bot user id
if [ "${DISCORD_MULTI_SHOGUN:-false}" = "true" ]; then
  if [ -n "$DISCORD_BOT_USER_ID" ]; then
    BOT_USER_ID="$DISCORD_BOT_USER_ID"
  else
    BOT_USER_ID=$(python3 -c "
import os, urllib.request, json
token = os.environ['DISCORD_BOT_TOKEN']
req = urllib.request.Request('https://discord.com/api/v10/users/@me',
  headers={'Authorization': f'Bot {token}'})
resp = urllib.request.urlopen(req)
print(json.loads(resp.read())['id'])
" 2>/dev/null)
    if [ -z "$BOT_USER_ID" ]; then
      echo "ERROR: Cannot resolve bot user id. Set DISCORD_BOT_USER_ID or fix token." >&2
      exit 1
    fi
  fi
  export DISCORD_BOT_USER_ID="$BOT_USER_ID"
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
# Writes API response to tmpfile to avoid ARG_MAX limit with large JSON payloads.
parse_messages() {
    local _pm_tmpfile
    _pm_tmpfile=$(mktemp /tmp/discord_response_XXXXXX.json)
    printf '%s' "$1" > "$_pm_tmpfile"
    DISCORD_API_RESPONSE_FILE="$_pm_tmpfile" python3 - "$LORD_ID" <<'PY'
import os, sys, json

lord_id = sys.argv[1]
path = os.environ.get("DISCORD_API_RESPONSE_FILE", "")
try:
    with open(path) as _f:
        raw = _f.read()
    os.unlink(path)
except Exception:
    sys.exit(0)
try:
    data = json.loads(raw)
except Exception:
    sys.exit(0)
if not isinstance(data, list):
    sys.exit(0)
_multi = os.environ.get('DISCORD_MULTI_SHOGUN', 'false').lower() == 'true'
_bot_id = os.environ.get('DISCORD_BOT_USER_ID', '')
_role_id = os.environ.get('DISCORD_SHOGUN_ROLE_ID', '')
for msg in reversed(data):  # reversed: oldest first
    author = msg.get("author", {})
    if author.get("id") != lord_id:
        continue
    # 第2関門: 宛先ルーティング（multi モードのみ）
    if _multi:
        _me = msg.get('mention_everyone', False)
        _mentions = [m['id'] for m in msg.get('mentions', [])]
        _mroles = [r['id'] if isinstance(r, dict) else r
                   for r in msg.get('mention_roles', [])]
        _addressed = (
            _me or
            (_bot_id and _bot_id in _mentions) or
            (_role_id and _role_id in _mroles)
        )
        if not _addressed:
            print(f"SKIP:{msg['id']}")
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

append_discord_inbox_error() {
    local msg_id="$1"
    local ts="$2"
    local content="$3"
    local reason="$4"
    local error_at
    error_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    (
        if command -v flock &>/dev/null; then
            flock -w 5 200 || return 1
        else
            _ld="${LOCKFILE}.d"; _i=0
            while ! mkdir "$_ld" 2>/dev/null; do sleep 0.1; _i=$((_i+1)); [ $_i -ge 50 ] && return 1; done
            trap "rmdir '$_ld' 2>/dev/null" EXIT
        fi
        DISCORD_INBOX_PATH="$INBOX" \
        MSG_ID="$msg_id" \
        MSG_TS="$ts" \
        MSG_TEXT="$content" \
        ERR_TYPE="$reason" \
        ERR_AT="$error_at" \
        python3 - << 'PY'
import os, yaml, tempfile

path = os.environ["DISCORD_INBOX_PATH"]
entry = {
    "id": os.environ.get("MSG_ID", ""),
    "timestamp": os.environ.get("MSG_TS", ""),
    "message": os.environ.get("MSG_TEXT", ""),
    "status": "error",
    "error_type": os.environ.get("ERR_TYPE", "write_failed"),
    "error_at": os.environ.get("ERR_AT", ""),
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
    import sys
    print(f"[discord_listener] error-entry write failed: {e}", file=sys.stderr)
    sys.exit(1)
PY
    ) 200>"$LOCKFILE"
}

echo "[$(date)] discord_listener started — channel: ${CHANNEL_ID} — lord: ${LORD_ID}" >&2

LAST_WARNED_SKIP_ID=""
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
        # cmd_451: silent loss対策 — cycle単位の追跡変数初期化
        SKIP_ADVANCE_ID=""
        HAD_FAILURE=false
        # Process messages (filtered by LORD_ID)
        while IFS= read -r json_line; do
            [ -z "$json_line" ] && continue
            if [[ "$json_line" == SKIP:* ]]; then
              _skip_id="${json_line#SKIP:}"
              if [ "$_skip_id" != "$LAST_WARNED_SKIP_ID" ]; then
                echo "[listener] 宛先未指定のため無処理 (id=$_skip_id)。@将軍 か @everyone を付与されたし。" >&2
                LAST_WARNED_SKIP_ID="$_skip_id"
              fi
              # cmd_451: SKIP idは安全に前進可能(後続の失敗がある場合はbreakで上書きされない)
              SKIP_ADVANCE_ID="$_skip_id"
              continue
            fi
            msg_id=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d['id'])" "$json_line")
            ts=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d['ts'])" "$json_line")
            content=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d['content'])" "$json_line")
            [ -z "$msg_id" ] && continue
            echo "[$(date)] Received from Lord: ${content:0:50}" >&2

            if ! append_discord_inbox "$msg_id" "$ts" "$content"; then
                echo "[$(date)] WARNING: failed to write discord_inbox for $msg_id — state NOT advanced" >&2
                # cmd_451: (a)state非前進(breakでcycleを中断) (b)error可視化
                HAD_FAILURE=true
                append_discord_inbox_error "$msg_id" "$ts" "$content" "write_failed" || \
                    echo "[$(date)] WARNING: error-entry write also failed for $msg_id" >&2
                break
            fi

            # Update last_msg_id
            LAST_MSG_ID="$msg_id"
            echo "$LAST_MSG_ID" > "$STATE_FILE"

            # Wake shogun
            bash "$SCRIPT_DIR/scripts/inbox_write.sh" shogun \
                "Discordから新しいメッセージ受信。queue/discord_inbox.yaml を確認し処理せよ。" \
                discord_received discord_listener
        done < <(parse_messages "$RESPONSE")

        # cmd_451: 失敗したLordメッセージより前のSKIPのみ前進(LATEST_ID一括前進は廃止)
        if [ -n "$SKIP_ADVANCE_ID" ] && { [ -z "$LAST_MSG_ID" ] || [ "$SKIP_ADVANCE_ID" \> "$LAST_MSG_ID" ]; }; then
            LAST_MSG_ID="$SKIP_ADVANCE_ID"
            echo "$LAST_MSG_ID" > "$STATE_FILE"
        fi
    else
        echo "[$(date)] Discord API error: $(echo "$RESPONSE" | head -c 200)" >&2
        sleep 10  # Back off on error
    fi

    sleep "$POLL_INTERVAL"
done
