#!/bin/bash
# Send notifications via webhook on Claude Code events.
# Triggered by Notification events (JSON on stdin); positional args
# `notify.sh <event> <message>` are accepted for manual runs and tests.
# Configure CLAUDE_NOTIFY_WEBHOOK in the environment before use.

WEBHOOK_URL="${CLAUDE_NOTIFY_WEBHOOK:-}"
[ -z "$WEBHOOK_URL" ] && exit 0

if [ "$#" -ge 1 ]; then
    EVENT="${1:-unknown}"
    MESSAGE="${2:-Claude Code event occurred}"
else
    INPUT=$(cat)
    EVENT=$(jq -r '.notification_type // .hook_event_name // "unknown"' <<<"$INPUT" 2>/dev/null)
    MESSAGE=$(jq -r '.message // "Claude Code event occurred"' <<<"$INPUT" 2>/dev/null)
fi

# jq builds the payload so quotes or newlines in the message cannot break the JSON
PAYLOAD=$(jq -n \
    --arg text "[$EVENT] $MESSAGE" \
    --arg project "$(basename "${CLAUDE_PROJECT_DIR:-$(pwd)}")" \
    --arg branch "$(git branch --show-current 2>/dev/null || echo unknown)" \
    --arg timestamp "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{text: $text, project: $project, branch: $branch, timestamp: $timestamp}')

# Send notification (non-blocking)
curl -s -X POST "$WEBHOOK_URL" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" > /dev/null 2>&1 &
