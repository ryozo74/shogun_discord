#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# discord_autorespond.sh — standalone autonomous shogun responder
#
# For a shogun that runs WITHOUT the tmux multi-agent fleet (e.g. a
# 2nd shogun): watches queue/discord_inbox.yaml for `status: pending`
# entries (already filtered to this shogun's @mention by
# discord_listener.sh), generates a reply with headless `claude -p`,
# sends it via scripts/discord.sh, and marks the entry done.
#
# Idempotent / safe:
#  - single-instance guard (pidfile)
#  - on first start, pre-existing pending entries are marked `autoskip`
#    (assumed already handled) — only NEW messages get auto-answered
#  - claude run with tools disabled, timeout, retry cap
#  - stop:  rm -f the pidfile  OR  kill the logged PID
#
# Env (.env): optional AUTORESPOND_POLL (sec, default 5),
#             AUTORESPOND_MODEL (claude --model alias, optional),
#             AUTORESPOND_PERSONA (override system prompt)
# ═══════════════════════════════════════════════════════════════
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

set -a
[ -f "$SCRIPT_DIR/.env" ] && source "$SCRIPT_DIR/.env"
set +a

INBOX="$SCRIPT_DIR/queue/discord_inbox.yaml"
LOCKFILE="${INBOX}.lock"
LOG="$SCRIPT_DIR/queue/discord_autorespond.log"
PIDFILE="/tmp/discord_autorespond_$(echo "$SCRIPT_DIR" | md5sum | cut -c1-8).pid"
POLL="${AUTORESPOND_POLL:-5}"
MAX_RETRY=3

PY3="$SCRIPT_DIR/.venv/bin/python3"
[ -x "$PY3" ] || PY3="$(command -v python3 || echo python3)"

log() { echo "[$(date '+%F %T')] $*" | tee -a "$LOG" >&2; }

# ── single-instance guard ───────────────────────────────────────
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null; then
    log "already running (pid $(cat "$PIDFILE")) — exit"
    exit 0
fi
echo $$ > "$PIDFILE"
trap 'rm -f "$PIDFILE"; log "stopped"' EXIT

PERSONA_DEFAULT='あなたは「2nd将軍」(shogun_discord-second)。Discordで殿から届いた一言に戦国武将口調で簡潔(2〜5文)に返答する。tmux/ファイル操作/多エージェント手順は一切行わず、Discordへ送る返答本文のみを出力せよ。reply_to が与えられた場合、それは別の将軍の発言で、殿はそれへの所見を求めている。'
PERSONA="${AUTORESPOND_PERSONA:-$PERSONA_DEFAULT}"

MODEL_ARG=()
[ -n "${AUTORESPOND_MODEL:-}" ] && MODEL_ARG=(--model "$AUTORESPOND_MODEL")

# ── baseline: mark currently-pending as autoskip (already handled) ─
"$PY3" - "$INBOX" <<'PY'
import sys, yaml
p = sys.argv[1]
try:
    d = yaml.safe_load(open(p, encoding="utf-8")) or {}
except Exception:
    d = {}
n = 0
for e in d.get("inbox", []) or []:
    if e.get("status") == "pending":
        e["status"] = "autoskip"; n += 1
if n:
    yaml.safe_dump(d, open(p, "w", encoding="utf-8"),
                    default_flow_style=False, allow_unicode=True, sort_keys=False)
print(f"baseline: {n} pre-existing pending → autoskip")
PY

log "discord_autorespond started (pid $$, poll=${POLL}s, inbox=$INBOX)"

# ── next pending entry as JSON (id, message, reply_to) ──────────
next_pending() {
    "$PY3" - "$INBOX" <<'PY'
import sys, json, yaml
try:
    d = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
except Exception:
    sys.exit(0)
for e in d.get("inbox", []) or []:
    if e.get("status") == "pending":
        print(json.dumps({"id": e.get("id",""),
                           "message": e.get("message",""),
                           "reply_to": e.get("reply_to")}))
        break
PY
}

set_status() {  # $1=id $2=new_status
    (
        flock -w 5 200 || exit 1
        ID="$1" NEW="$2" "$PY3" - "$INBOX" <<'PY'
import os, sys, yaml
p = sys.argv[1]
d = yaml.safe_load(open(p, encoding="utf-8")) or {}
for e in d.get("inbox", []) or []:
    if e.get("id") == os.environ["ID"]:
        e["status"] = os.environ["NEW"]
yaml.safe_dump(d, open(p, "w", encoding="utf-8"),
                default_flow_style=False, allow_unicode=True, sort_keys=False)
PY
    ) 200>"$LOCKFILE"
}

STOPFILE="$SCRIPT_DIR/queue/discord_autorespond.stop"
declare -A RETRY
while true; do
    if [ -f "$STOPFILE" ]; then
        log "stop flag found ($STOPFILE) — graceful exit"; rm -f "$STOPFILE"; exit 0
    fi
    entry="$(next_pending)"
    if [ -z "$entry" ]; then sleep "$POLL"; continue; fi

    id=$("$PY3" -c "import json,sys;print(json.loads(sys.argv[1])['id'])" "$entry")
    msg=$("$PY3" -c "import json,sys;print(json.loads(sys.argv[1])['message'])" "$entry")
    rt=$("$PY3" -c "import json,sys;d=json.loads(sys.argv[1]).get('reply_to');print('参照元(%s): %s'%(d.get('author',''),d.get('content','')) if d else '')" "$entry")

    log "processing id=$id msg=${msg:0:60}"
    prompt="殿の発言:「${msg}」"
    [ -n "$rt" ] && prompt="${prompt}"$'\n'"${rt}"

    reply="$(timeout 180 claude -p --no-session-persistence \
               --disallowedTools "Bash Edit Write WebFetch WebSearch" \
               "${MODEL_ARG[@]}" \
               --append-system-prompt "$PERSONA" "$prompt" 2>>"$LOG")"
    rc=$?

    if [ $rc -ne 0 ] || [ -z "${reply// /}" ]; then
        RETRY[$id]=$(( ${RETRY[$id]:-0} + 1 ))
        log "generation failed id=$id rc=$rc try=${RETRY[$id]}"
        if [ "${RETRY[$id]}" -ge "$MAX_RETRY" ]; then
            set_status "$id" "failed"; log "id=$id → failed (gave up)"
        else
            sleep "$POLL"
        fi
        continue
    fi

    reply="${reply:0:1800}"   # Discord 2000-char safety
    if bash "$SCRIPT_DIR/scripts/discord.sh" "🏯 $reply" >>"$LOG" 2>&1; then
        set_status "$id" "done"
        log "id=$id → answered & sent"
    else
        RETRY[$id]=$(( ${RETRY[$id]:-0} + 1 ))
        log "discord send failed id=$id try=${RETRY[$id]}"
        [ "${RETRY[$id]}" -ge "$MAX_RETRY" ] && { set_status "$id" "failed"; log "id=$id → failed (send)"; }
    fi
    sleep "$POLL"
done
