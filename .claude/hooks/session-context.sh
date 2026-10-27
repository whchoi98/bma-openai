#!/bin/bash
# Load project context at Claude Code session start.
# SessionStart stdout is added to Claude's context, so keep it short and factual.

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" 2>/dev/null || exit 0

echo "=== Project Context ==="

PY_NAME=$(sed -n 's/^name = "\(.*\)"/\1/p' pyproject.toml 2>/dev/null | head -1)
PY_VER=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml 2>/dev/null | head -1)
WEB_NAME=$(jq -r '.name // empty' web/package.json 2>/dev/null)
echo "Project: ${PY_NAME:-$(basename "$(pwd)")} ${PY_VER} (Python 3.12) + ${WEB_NAME:-web} (Node.js 24)"
echo "Regions: app/BMA/Runtime us-east-1, read-only target ap-northeast-2"

# Recent activity
LAST_COMMIT=$(git log -1 --format="%h %s (%cr)" 2>/dev/null)
[ -n "$LAST_COMMIT" ] && echo "Last commit: $LAST_COMMIT"

BRANCH=$(git branch --show-current 2>/dev/null)
[ -n "$BRANCH" ] && echo "Branch: $BRANCH"

CHANGES=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
[ "${CHANGES:-0}" -gt 0 ] && echo "Uncommitted changes: $CHANGES file(s)"

# Environment readiness
[ -x .venv/bin/python ] || echo "Warning: .venv missing - run: bash scripts/setup.sh"
[ -d web/node_modules ] || echo "Warning: web/node_modules missing - run: npm ci --ignore-scripts --prefix web"
[ -f artifacts/deployment-context.json ] && echo "Deployment context: artifacts/deployment-context.json (live account pinned)"

# Documentation status
CLAUDE_COUNT=$(find . -name "CLAUDE.md" -not -path "./.git/*" -not -path "./.venv/*" -not -path "*/node_modules/*" 2>/dev/null | wc -l | tr -d ' ')
ADR_COUNT=$(find docs/decisions -name 'ADR-*.md' 2>/dev/null | wc -l | tr -d ' ')
echo "CLAUDE.md files: $CLAUDE_COUNT, ADRs: $ADR_COUNT"

echo "======================"
