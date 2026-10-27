#!/bin/bash
# Project setup script for new developers.
# Usage: bash scripts/setup.sh
# Installs local dependencies only; makes no AWS API or model calls.

set -e

cd "$(dirname "$0")/.."

echo "=== Project Setup ==="

# Check prerequisites
command -v git >/dev/null 2>&1 || { echo "ERROR: git is required"; exit 1; }
command -v node >/dev/null 2>&1 || { echo "ERROR: Node.js 24 is required"; exit 1; }
NODE_MAJOR=$(node -p 'process.versions.node.split(".")[0]')
[ "$NODE_MAJOR" -ge 24 ] || { echo "ERROR: Node.js 24+ is required (found $(node --version))"; exit 1; }

# Python dependencies (pyproject.toml, Python 3.12)
echo "Installing Python dependencies..."
if command -v uv >/dev/null 2>&1; then
    [ -x .venv/bin/python ] || uv venv --python 3.12 .venv
    uv pip install --python .venv/bin/python -e '.[dev]'
else
    PY=$(command -v python3.12 || command -v python3)
    "$PY" -c 'import sys; sys.exit(sys.version_info[:2] < (3, 12))' \
        || { echo "ERROR: Python 3.12+ is required"; exit 1; }
    [ -x .venv/bin/python ] || "$PY" -m venv .venv
    .venv/bin/pip install -e '.[dev]'
fi

# Node.js dependencies for the Web Function (lockfile, no install scripts)
echo "Installing Node.js dependencies..."
npm ci --ignore-scripts --prefix web

# Setup environment
if [ -f ".env.example" ] && [ ! -f ".env" ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
    chmod 600 .env
    echo "IMPORTANT: Nothing loads .env automatically. Use 'set -a; . ./.env; set +a' when needed."
    echo "           Local runs normally use DATA_MODE=sample, which needs no AWS values."
fi

# Claude hooks
if [ -f ".claude/hooks/check-doc-sync.sh" ]; then
    chmod +x .claude/hooks/*.sh
    echo "Claude hooks configured"
fi

# Git hooks (commit-msg, pre-commit)
if [ -d ".git" ] && [ -f "scripts/install-hooks.sh" ]; then
    bash scripts/install-hooks.sh
fi

echo "=== Setup Complete ==="
echo "Next steps:"
echo "  1. Run the tests: .venv/bin/python -m pytest && npm test --prefix web"
echo "  2. Start sample mode: npm run build --prefix web && DATA_MODE=sample node web/index.js"
echo "  3. Read CLAUDE.md and docs/onboarding.md"
