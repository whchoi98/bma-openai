#!/bin/bash
# Tests for .claude/hooks/*.sh (sourced by tests/run-all.sh)

# --- Existence and permissions ---
HOOKS=(check-doc-sync secret-scan session-context notify)
for hook in "${HOOKS[@]}"; do
    assert_file_exists "$hook.sh exists" ".claude/hooks/$hook.sh"
    assert_file_executable "$hook.sh is executable" ".claude/hooks/$hook.sh"
    assert_bash_syntax "$hook.sh valid bash" ".claude/hooks/$hook.sh"
done

# --- settings.json hook registration ---
assert_file_exists "settings.json exists" ".claude/settings.json"
assert_json_valid "settings.json is valid JSON" ".claude/settings.json"

SETTINGS=$(cat .claude/settings.json)
assert_contains "SessionStart hook registered" "$SETTINGS" "session-context.sh"
assert_contains "PreToolUse hook registered" "$SETTINGS" "secret-scan.sh"
assert_contains "PostToolUse hook registered" "$SETTINGS" "check-doc-sync.sh"
assert_contains "PostToolUse matcher is Write|Edit" "$SETTINGS" "Write|Edit"
assert_contains "Notification hook registered" "$SETTINGS" "notify.sh"

# The PreToolUse command must propagate exit 2, so it must not swallow the status
PRE_CMD=$(jq -r '.hooks.PreToolUse[0].hooks[0].command' .claude/settings.json)
assert_not_contains "PreToolUse command keeps exit status" "$PRE_CMD" "|| true"
assert_eq "PreToolUse matcher is Bash" "Bash" "$(jq -r '.hooks.PreToolUse[0].matcher' .claude/settings.json)"

DENY=$(jq -r '.permissions.deny[]' .claude/settings.json)
assert_contains "deny: rm -rf" "$DENY" "Bash(rm -rf:*)"
assert_contains "deny: delete-stack" "$DENY" "Bash(aws cloudformation delete-stack:*)"
assert_contains "deny: read deployment secrets" "$DENY" "Read(./artifacts/deployment-secrets.json)"

# --- check-doc-sync behavior ---
OUTPUT=$(bash .claude/hooks/check-doc-sync.sh "" 2>&1 || true)
assert_eq "check-doc-sync: empty path produces no output" "" "$OUTPUT"

OUTPUT=$(echo "{\"tool_input\":{\"file_path\":\"$PROJECT_ROOT/web/ui/app.js\"}}" \
    | bash .claude/hooks/check-doc-sync.sh 2>&1 || true)
assert_eq "check-doc-sync: nested file under documented module is quiet" "" "$OUTPUT"

OUTPUT=$(bash .claude/hooks/check-doc-sync.sh "aws_inventory/engine.py" 2>&1 || true)
assert_not_contains "check-doc-sync: module root CLAUDE.md is found" "$OUTPUT" "CLAUDE.md is missing"

OUTPUT=$(echo "{\"tool_input\":{\"file_path\":\"$PROJECT_ROOT/infra/template.yaml\"}}" \
    | bash .claude/hooks/check-doc-sync.sh 2>&1 || true)
CONTEXT=$(echo "$OUTPUT" | jq -r '.hookSpecificOutput.additionalContext // empty' 2>/dev/null || true)
assert_eq "check-doc-sync: hook mode emits PostToolUse JSON" "PostToolUse" \
    "$(echo "$OUTPUT" | jq -r '.hookSpecificOutput.hookEventName // empty' 2>/dev/null || true)"
assert_contains "check-doc-sync: infra change points to runbook" "$CONTEXT" "deploy-production.md"

# --- secret-scan behavior (PreToolUse mode, isolated git repo) ---
OUTPUT=$(echo '{"tool_input":{"command":"ls -la"}}' | bash .claude/hooks/secret-scan.sh 2>&1; echo "exit=$?")
assert_eq "secret-scan: non-commit command passes silently" "exit=0" "$OUTPUT"

SCAN_REPO="$TEST_TMP/scan-repo"
mkdir -p "$SCAN_REPO"
git -C "$SCAN_REPO" init -q
echo 'print("hello")' > "$SCAN_REPO/clean.py"
git -C "$SCAN_REPO" add clean.py
STATUS=$(echo '{"tool_input":{"command":"git commit -m test"}}' \
    | CLAUDE_PROJECT_DIR="$SCAN_REPO" bash .claude/hooks/secret-scan.sh >/dev/null 2>&1; echo $?)
assert_eq "secret-scan: clean staged files allow commit" "0" "$STATUS"

AWS_KEY_PREFIX="AKIA"
AWS_KEY_BODY="IOSFODNN7EXAMPLE"
echo "key = \"${AWS_KEY_PREFIX}${AWS_KEY_BODY}\"" > "$SCAN_REPO/leak.py"
STATUS=$(echo '{"tool_input":{"command":"git add -A && git commit -m test"}}' \
    | CLAUDE_PROJECT_DIR="$SCAN_REPO" bash .claude/hooks/secret-scan.sh >/dev/null 2>&1; echo $?)
assert_eq "secret-scan: unstaged secret in 'git add && commit' blocks with exit 2" "2" "$STATUS"

git -C "$SCAN_REPO" add leak.py
STATUS=$(bash -c "cd '$SCAN_REPO' && bash '$PROJECT_ROOT/.claude/hooks/secret-scan.sh' --staged" >/dev/null 2>&1; echo $?)
assert_eq "secret-scan: --staged (git pre-commit) blocks with exit 1" "1" "$STATUS"

# --- session-context ---
OUTPUT=$(bash .claude/hooks/session-context.sh 2>&1 || true)
assert_contains "session-context: shows project header" "$OUTPUT" "Project Context"
assert_contains "session-context: shows project name" "$OUTPUT" "bma-seoul-inventory"
assert_contains "session-context: shows region split" "$OUTPUT" "ap-northeast-2"

# --- notify ---
OUTPUT=$(CLAUDE_NOTIFY_WEBHOOK="" bash .claude/hooks/notify.sh "test" "msg" 2>&1 || true)
assert_eq "notify.sh: no webhook URL produces no output" "" "$OUTPUT"
