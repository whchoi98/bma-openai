#!/bin/bash
# Scan files for secrets before they are committed.
#
# Modes:
#   (no args)        PreToolUse hook (matcher: Bash). Reads the event JSON on stdin and
#                    only acts on `git commit` commands. Exit 2 blocks the tool call and
#                    returns the reason to Claude on stderr.
#   --staged         Git pre-commit hook (installed by scripts/install-hooks.sh). Exit 1 blocks.
#   --files F [F..]  Scan the given files (manual runs and tests). Exit 1 if secrets are found.

PATTERNS=(
    'AKIA[0-9A-Z]{16}'                                              # AWS Access Key ID
    'aws_secret_access_key\s{0,5}[=:]\s{0,5}["\x27]?[A-Za-z0-9/+=]{40}' # AWS Secret Key (context-aware)
    'sk-[A-Za-z0-9]{20}T3BlbkFJ[A-Za-z0-9]{20}'                     # OpenAI API Key
    'sk-ant-[A-Za-z0-9-]{90,}'                                      # Anthropic API Key
    'ghp_[A-Za-z0-9]{36}'                                           # GitHub Personal Access Token
    'gho_[A-Za-z0-9]{36}'                                           # GitHub OAuth Token
    'github_pat_[A-Za-z0-9_]{82}'                                   # GitHub Fine-grained PAT
    'xoxb-[0-9]+-[A-Za-z0-9]+'                                      # Slack Bot Token
    'xoxp-[0-9]+-[A-Za-z0-9]+'                                      # Slack User Token
    'sk_live_[A-Za-z0-9]{24,}'                                      # Stripe Secret Key
    'rk_live_[A-Za-z0-9]{24,}'                                      # Stripe Restricted Key
    'AIza[A-Za-z0-9_-]{35}'                                         # Google API Key
    'ya29\.[A-Za-z0-9_-]{50,}'                                      # Google OAuth Token
    'DefaultEndpointsProtocol=https;Account'                        # Azure Connection String
    'password\s*[:=]\s*["\x27][^"\x27]{8,}'                         # Password assignments
    'secret\s*[:=]\s*["\x27][^"\x27]{8,}'                           # Secret assignments
    'api[_-]?key\s*[:=]\s*["\x27][^"\x27]{8,}'                      # API key assignments
)

# Files to skip: templates, docs, lockfiles, and the scanner's own test material
SKIP_PATTERNS=('.env.example' '*secret-scan.sh' '*.md' '*package-lock.json' '*yarn.lock'
               'tests/fixtures/*' 'tests/hooks/test-secret-patterns.sh')

# Never commit these regardless of content
FORBIDDEN_PATHS=('.env' 'artifacts/deployment-secrets.json' 'artifacts/deploy-parameters.json')

scan_files() {
    local found=0 file pattern regex skip
    for file in "$@"; do
        skip=false
        for pattern in "${SKIP_PATTERNS[@]}"; do
            [[ "$file" == $pattern ]] && skip=true && break
        done
        $skip && continue
        for pattern in "${FORBIDDEN_PATHS[@]}"; do
            if [ "$file" = "$pattern" ]; then
                echo "[secret-scan] $file must never be committed" >&2
                found=1
            fi
        done
        [ -f "$file" ] || continue
        for regex in "${PATTERNS[@]}"; do
            # -I skips binary files
            if grep -IqP -- "$regex" "$file" 2>/dev/null; then
                echo "[secret-scan] Potential secret found in $file (pattern: ${regex:0:30}...)" >&2
                found=1
            fi
        done
    done
    return $found
}

report_blocked() {
    echo "" >&2
    echo "[secret-scan] BLOCKED: Potential secrets detected in files about to be committed." >&2
    echo "[secret-scan] Remove the secrets, keep them in .env or artifacts/ (both gitignored)," >&2
    echo "[secret-scan] and use .env.example for placeholders." >&2
}

case "${1:-}" in
    --files)
        shift
        scan_files "$@" || { report_blocked; exit 1; }
        exit 0
        ;;
    --staged)
        mapfile -t FILES < <(git diff --cached --name-only --diff-filter=ACM 2>/dev/null)
        [ "${#FILES[@]}" -eq 0 ] && exit 0
        scan_files "${FILES[@]}" || { report_blocked; exit 1; }
        exit 0
        ;;
esac

# PreToolUse mode
COMMAND=$(jq -r '.tool_input.command // empty' 2>/dev/null)
[[ "$COMMAND" =~ git[[:space:]]+([^|;&]*[[:space:]])?commit ]] || exit 0

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" 2>/dev/null || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

mapfile -t FILES < <(git diff --cached --name-only --diff-filter=ACM 2>/dev/null)
# `git add ... && git commit` or `commit -a` stages files after this hook runs,
# so include modified and untracked (non-ignored) files as well.
if [[ "$COMMAND" =~ git[[:space:]]+add || "$COMMAND" =~ commit[[:space:]].*[[:space:]](-[a-zA-Z]*a[a-zA-Z]*|--all)([[:space:]]|$) ]]; then
    mapfile -t -O "${#FILES[@]}" FILES < <(git ls-files -m -o --exclude-standard 2>/dev/null)
fi
[ "${#FILES[@]}" -eq 0 ] && exit 0

mapfile -t FILES < <(printf '%s\n' "${FILES[@]}" | sort -u)
scan_files "${FILES[@]}" || { report_blocked; exit 2; }
exit 0
