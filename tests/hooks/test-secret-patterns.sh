#!/bin/bash
# True/false positive tests for .claude/hooks/secret-scan.sh, run against the real scanner
# (sourced by tests/run-all.sh). Samples are assembled at runtime from tests/fixtures/.

SCANNER=".claude/hooks/secret-scan.sh"

# --- True positives: each sample must be detected ---
while IFS=$'\t' read -r name prefix body; do
    [[ -z "$name" || "$name" == \#* ]] && continue
    sample="$TEST_TMP/tp-sample.txt"
    printf '%s%s\n' "$prefix" "$body" > "$sample"
    bash "$SCANNER" --files "$sample" >/dev/null 2>&1 \
        && fail "TP: $name" "scanner did not detect the sample" \
        || pass "TP: $name"
done < tests/fixtures/secret-samples.txt

# --- False positives: none of these lines may trigger ---
while IFS= read -r line; do
    [ -z "$line" ] && continue
    sample="$TEST_TMP/fp-sample.txt"
    printf '%s\n' "$line" > "$sample"
    bash "$SCANNER" --files "$sample" >/dev/null 2>&1 \
        && pass "FP: ${line:0:40}" \
        || fail "FP: ${line:0:40}" "scanner flagged a non-secret"
done < tests/fixtures/false-positives.txt

# --- Skip and forbidden-path rules ---
bash "$SCANNER" --files .env.example >/dev/null 2>&1 \
    && pass "skip: .env.example is not scanned" || fail "skip: .env.example is not scanned" "flagged"
bash "$SCANNER" --files tests/fixtures/secret-samples.txt >/dev/null 2>&1 \
    && pass "skip: fixture files are not scanned" || fail "skip: fixture files are not scanned" "flagged"
bash "$SCANNER" --files artifacts/deployment-secrets.json >/dev/null 2>&1 \
    && fail "forbidden: artifacts/deployment-secrets.json is always blocked" "allowed" \
    || pass "forbidden: artifacts/deployment-secrets.json is always blocked"

# --- Regression: the AWS secret pattern must compile in PCRE (no variable-length lookbehind) ---
# grep exits 1 for "no match" and 2 for a pattern error; the runner uses set -e, so capture the status.
AWS_SECRET_REGEX=$(grep -oP "^\s+'\Kaws_secret_access_key[^']*" "$SCANNER" | head -1 || true)
REGEX_STATUS=0
echo "x" | grep -P -- "$AWS_SECRET_REGEX" >/dev/null 2>&1 || REGEX_STATUS=$?
if [ -n "$AWS_SECRET_REGEX" ] && [ "$REGEX_STATUS" -le 1 ]; then
    pass "AWS secret regex compiles"
else
    fail "AWS secret regex compiles" "pattern missing or grep -P error (status $REGEX_STATUS)"
fi
