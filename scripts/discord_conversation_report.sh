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

# ── 殿御下命 2026-08-21: 「報告があるときのみ投稿でよし」 ──────────────
# 自律巡回(/loop)中、機械が注入する user ロールのテキスト(skill本文・
# task-notification・system-reminder 等)を「殿の発言」と誤認して投稿し、
# Discord が垂れ流しになった。二重の門で塞ぐ。
#   門1: そのターンを起こしたのが本当に殿か(機械の注入なら投稿せぬ)
#   門2: 将軍の返しに中身があるか(「巡回を続け申す」級の相槌は投稿せぬ)
# ★真の報告は将軍が scripts/discord.sh で明示的に送る。本hookは
#   殿との生のやり取りを控えとして残すためだけのものである。
_MACHINE_MARKERS = (
    'SYSTEM NOTIFICATION', 'task-notification', 'system-reminder',
    'Monitor event', 'local-command-caveat', 'command-name',
    '— schedule a recurring', 'Launching skill:',
)
_probe = user_msg[:2000]
if not user_msg:
    sys.exit(0)                      # 門0: 殿の発言が無いターン(自律巡回の
                                     #      起床・task-notification 等)は
                                     #      写す会話が無い → 沈黙
if any(m in _probe for m in _MACHINE_MARKERS) or user_msg.startswith('/'):
    sys.exit(0)                      # 門1: 殿の発言ではない → 沈黙

MIN_REPORT_CHARS = 200
if len(assistant_msg) < MIN_REPORT_CHARS:
    sys.exit(0)                      # 門2: 報告の体を成さぬ → 沈黙

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
