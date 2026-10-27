#!/bin/bash
# Install Git hooks.
# Usage: bash scripts/install-hooks.sh

set -e

cd "$(dirname "$0")/.."

HOOKS_DIR=".git/hooks"

if [ ! -d "$HOOKS_DIR" ]; then
    echo "ERROR: .git/hooks directory not found. Is this a git repository?"
    exit 1
fi

# Install commit-msg hook (removes Co-Authored-By lines)
cat > "$HOOKS_DIR/commit-msg" << 'HOOK'
#!/bin/bash
# Remove Co-Authored-By lines from commit messages.
# Prevents Claude and other AI assistants from appearing as contributors.
sed -i '/^[Cc]o-[Aa]uthored-[Bb]y:.*/d' "$1"
sed -i -e :a -e '/^\n*$/{$d;N;ba' -e '}' "$1"
HOOK
chmod +x "$HOOKS_DIR/commit-msg"
echo "Installed commit-msg hook (AI co-author removal)"

# Install pre-commit hook (secret scan of staged files, independent of Claude Code)
cat > "$HOOKS_DIR/pre-commit" << 'HOOK'
#!/bin/bash
# Block commits whose staged files contain secret-like strings.
exec bash "$(git rev-parse --show-toplevel)/.claude/hooks/secret-scan.sh" --staged
HOOK
chmod +x "$HOOKS_DIR/pre-commit"
echo "Installed pre-commit hook (secret scan)"

echo "=== Git hooks installed ==="
