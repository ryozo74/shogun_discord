#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# discord_conversation_report.sh — Stop hook for top-level (Lord-facing) Claude session
# After each turn, posts the Lord's input + the assistant's response summary to
# DISCORD_CMD_CHANNEL_ID so the Lord can review the session from Discord.
#
# Skipped for tmux-hosted agents (ashigaru/karo/gunshi/shogun panes) — those have
# TMUX_PANE set and are handled by stop_hook_inbox.sh.
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Skip if running inside a tmux pane (multi-agent system)
if [ -n "${TMUX_PANE:-}" ] || [ -n "${TMUX:-}" ]; then
    exit 0
fi

INPUT=$(cat)

SUMMARY=$(STOP_HOOK_INPUT="$INPUT" python3 - <<'PY' 2>/dev/null
import os, sys, json

raw = os.environ.get('STOP_HOOK_INPUT', '')
try:
    data = json.loads(raw)
except Exception:
    sys.exit(0)

transcript_path = data.get('transcript_path', '')
assistant_msg = (data.get('last_assistant_message') or '').strip()

user_msg = ''
if transcript_path and os.path.exists(transcript_path):
    try:
        with open(transcript_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        for line in reversed(lines):
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if entry.get('type') != 'user':
                continue
            msg = entry.get('message', {})
            content = msg.get('content', '')
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                texts = []
                for c in content:
                    if isinstance(c, dict) and c.get('type') == 'text':
                        texts.append(c.get('text', ''))
                text = ' '.join(texts)
            else:
                text = ''
            text = text.strip()
            if not text or text.startswith('<') or 'tool_use_id' in text[:100]:
                continue
            user_msg = text
            break
    except Exception:
        pass

def trunc(s, n):
    return s if len(s) <= n else s[:n] + '…'

if not user_msg and not assistant_msg:
    sys.exit(0)

parts = []
if user_msg:
    parts.append(f'**殿:** {trunc(user_msg, 400)}')
if assistant_msg:
    parts.append(f'**将軍:** {trunc(assistant_msg, 1200)}')

out = '\n\n'.join(parts)
print(out[:1900])
PY
) || exit 0

if [ -z "$SUMMARY" ]; then
    exit 0
fi

nohup bash "$SCRIPT_DIR/scripts/discord.sh" "$SUMMARY" > /dev/null 2>&1 &
disown 2>/dev/null || true

exit 0
