#!/bin/bash
# Detect documentation sync needs after file changes.
# Triggered by PostToolUse (Write|Edit). Claude Code passes the event as JSON on
# stdin; a path argument is accepted for manual runs and tests.
# Walks parent directories (module root included) to find CLAUDE.md before warning.

if [ "$#" -ge 1 ]; then
    FILE_PATH="$1"
    FROM_HOOK=false
else
    FILE_PATH=$(jq -r '.tool_input.file_path // empty' 2>/dev/null)
    FROM_HOOK=true
fi
[ -z "$FILE_PATH" ] && exit 0

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$PROJECT_DIR" 2>/dev/null || exit 0
FILE_PATH="${FILE_PATH#"$PROJECT_DIR"/}"
FILE_PATH="${FILE_PATH#./}"

# Top-level source directories of this project. Each one is itself a module and
# owns a CLAUDE.md. webapp/static/ and studio/web/ ship inside Web Function ZIPs,
# so their docs live in webapp/CLAUDE.md and studio/CLAUDE.md instead.
SOURCE_ROOTS="aws_inventory webapp web runtime infra scripts skills tests studio"

MESSAGES=()

IS_SOURCE=false
for ROOT in $SOURCE_ROOTS; do
    if [[ "$FILE_PATH" == ${ROOT}/* ]]; then
        IS_SOURCE=true
        DIR=$(dirname "$FILE_PATH")
        FOUND_CLAUDE=false
        CHECK_DIR="$DIR"
        while [ "$CHECK_DIR" != "." ] && [ -n "$CHECK_DIR" ]; do
            if [ -f "$CHECK_DIR/CLAUDE.md" ]; then
                FOUND_CLAUDE=true
                break
            fi
            [ "$CHECK_DIR" = "$ROOT" ] && break
            CHECK_DIR=$(dirname "$CHECK_DIR")
        done
        if ! $FOUND_CLAUDE; then
            MESSAGES+=("[doc-sync] $ROOT/CLAUDE.md is missing. Create module documentation.")
        fi
        break
    fi
done

# Alert if no ADRs exist when source or architecture files change
if $IS_SOURCE || [[ "$FILE_PATH" == docs/architecture.md ]]; then
    ADR_COUNT=$(find docs/decisions -name 'ADR-*.md' 2>/dev/null | wc -l)
    if [ "$ADR_COUNT" -eq 0 ]; then
        MESSAGES+=("[doc-sync] No ADRs found. Record architectural decisions with /add-adr.")
    fi
fi

# Infrastructure changes must be reflected in runbooks and architecture docs
if [[ "$FILE_PATH" == studio/infra/*.yaml || "$FILE_PATH" == studio/RuntimeDockerfile ]]; then
    MESSAGES+=("[doc-sync] Studio infrastructure changed: check docs/architecture.md (AI Document Studio), docs/runbooks/deploy-document-studio.md and, for CloudFront behaviors, docs/runbooks/cloudfront-oac.md.")
elif [[ "$FILE_PATH" == */Dockerfile || "$FILE_PATH" == Dockerfile* || "$FILE_PATH" == infra/*.yaml ]]; then
    RUNBOOK_COUNT=$(find docs/runbooks -name '*.md' -not -name '.template.md' 2>/dev/null | wc -l)
    if [ "$RUNBOOK_COUNT" -eq 0 ]; then
        MESSAGES+=("[doc-sync] No runbooks found. Create operational runbooks for deployment/recovery.")
    fi
    MESSAGES+=("[doc-sync] Infrastructure changed: check docs/architecture.md (Infrastructure), docs/runbooks/deploy-production.md and, for CloudFront behaviors, docs/runbooks/cloudfront-oac.md.")
fi

[ "${#MESSAGES[@]}" -eq 0 ] && exit 0

if $FROM_HOOK; then
    # additionalContext reaches Claude without blocking the completed tool call
    printf '%s\n' "${MESSAGES[@]}" | jq -Rs '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: .}}'
else
    printf '%s\n' "${MESSAGES[@]}"
fi
exit 0
