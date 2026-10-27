#!/bin/bash
# Project structure integrity tests (sourced by tests/run-all.sh)

# --- Manifest validation ---
assert_json_valid "settings.json is valid JSON" ".claude/settings.json"
assert_json_valid ".mcp.json is valid JSON" ".mcp.json"
assert_json_valid "web/package.json is valid JSON" "web/package.json"

# --- Version consistency (pyproject.toml vs web/package.json) ---
PY_VER=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)
WEB_VER=$(jq -r '.version' web/package.json)
assert_eq "Version sync: pyproject.toml == web/package.json" "$PY_VER" "$WEB_VER"
grep -qF "Version-${PY_VER}-" README.md && pass "README version badge matches $PY_VER" \
    || fail "README version badge matches $PY_VER" "badge not found"

# --- File existence ---
for f in CLAUDE.md README.md CHANGELOG.md LICENSE .editorconfig .env.example .gitignore .dockerignore \
         docs/architecture.md docs/onboarding.md docs/api-reference.md \
         docs/decisions/.template.md docs/runbooks/.template.md docs/runbooks/deploy-production.md \
         docs/reference/INDEX.md docs/runbooks/deploy-document-studio.md docs/document-studio.md \
         studio/README.md studio/examples/monthly-sales.xlsx studio/examples/monthly-sales-en.xlsx \
         docs/cloudfront-deployment.md docs/runbooks/cloudfront-oac.md; do
    assert_file_exists "$f" "$f"
done

# --- Module CLAUDE.md for every source root (none inside the zipped static tree) ---
for module in aws_inventory webapp web runtime infra scripts skills tests studio; do
    assert_file_exists "Module doc: $module/CLAUDE.md" "$module/CLAUDE.md"
done
STATIC_DOCS=$(find webapp/static studio/web -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
assert_eq "webapp/static/ and studio/web/ contain no Markdown (shipped in Web Function ZIPs)" "0" "$STATIC_DOCS"

# --- Runtime image must not receive Claude files ---
DOCKERIGNORE=$(cat .dockerignore)
assert_contains ".dockerignore excludes **/CLAUDE.md" "$DOCKERIGNORE" "**/CLAUDE.md"
assert_contains ".dockerignore excludes .claude" "$DOCKERIGNORE" ".claude"

# --- .gitignore keeps secrets out ---
GITIGNORE=$(cat .gitignore)
for pattern in ".env" "artifacts/" ".claude/settings.local.json" "runtime/bin/"; do
    assert_contains ".gitignore has $pattern" "$GITIGNORE" "$pattern"
done
git check-ignore -q studio/node_modules \
    && pass ".gitignore covers the studio/node_modules symlink" || fail ".gitignore covers the studio/node_modules symlink" "not ignored"

# --- Script validation ---
for script in scripts/setup.sh scripts/install-hooks.sh tests/run-all.sh; do
    assert_file_executable "$script is executable" "$script"
    assert_bash_syntax "$script valid bash" "$script"
done

# --- Command frontmatter ---
for cmd in review test-all deploy; do
    CMD_CONTENT=$(cat ".claude/commands/$cmd.md")
    assert_contains "Command $cmd: has frontmatter" "$CMD_CONTENT" "description:"
    assert_contains "Command $cmd: has allowed-tools" "$CMD_CONTENT" "allowed-tools:"
done
DEPLOY_TOOLS=$(sed -n 's/^allowed-tools: //p' .claude/commands/deploy.md)
assert_not_contains "Command deploy: stack deploy is not pre-allowed" "$DEPLOY_TOOLS" "cloudformation"

# --- Skill and agent frontmatter ---
for skill in code-review refactor release sync-docs; do
    assert_eq "Skill $skill: name matches directory" "$skill" \
        "$(sed -n 's/^name: //p' ".claude/skills/$skill/SKILL.md" | head -1)"
    grep -q '^description: .\{20,\}' ".claude/skills/$skill/SKILL.md" \
        && pass "Skill $skill: has description" || fail "Skill $skill: has description" "missing"
done
for agent in code-reviewer security-auditor; do
    assert_file_exists "Agent $agent.md exists" ".claude/agents/$agent.md"
    head -1 ".claude/agents/$agent.md" | grep -q '^---$' \
        && pass "Agent $agent: has frontmatter" || fail "Agent $agent: has frontmatter" "missing"
done

# --- CLAUDE.md content (use grep -F for fixed string matching) ---
SECTIONS=("Overview" "Tech Stack" "Project Structure" "Conventions" "Key Commands" "Auto-Sync Rules")
for section in "${SECTIONS[@]}"; do
    grep -qF "## $section" CLAUDE.md && pass "CLAUDE.md: has $section" || fail "CLAUDE.md: has $section" "not found"
done
LINES=$(wc -l < CLAUDE.md | tr -d ' ')
[ "$LINES" -le 500 ] && pass "CLAUDE.md under 500 lines ($LINES)" || fail "CLAUDE.md under 500 lines" "$LINES lines"
grep -qF "<!-- AUTO-MANAGED:references -->" CLAUDE.md \
    && pass "CLAUDE.md: has references AUTO-MANAGED block" || fail "CLAUDE.md: has references AUTO-MANAGED block" "missing"

# --- Reference docs: every linked layer exists and every Code Pointer resolves ---
for layer in $(grep -oP 'docs/reference/\K[a-z-]+(?=\.md\))' CLAUDE.md | grep -v '^INDEX$'); do
    assert_file_exists "Reference layer: $layer" "docs/reference/$layer.md"
done
BAD_POINTERS=""
for ref in docs/reference/*.md; do
    [ "$(basename "$ref")" = "INDEX.md" ] && continue
    while IFS= read -r pointer; do
        path="${pointer%%:*}"
        line="${pointer#"$path"}"; line="${line#:}"
        if [ ! -e "$path" ]; then
            BAD_POINTERS+=" $ref->$pointer"
        elif [ -n "$line" ] && [ "$(wc -l < "$path")" -lt "${line%%-*}" ]; then
            BAD_POINTERS+=" $ref->$pointer(line)"
        fi
    done < <(sed -n '/^### 4\./,/^### 5\./p' "$ref" | grep -oP '^- `\K[^`]+(?=`)' | grep -E '^[A-Za-z0-9_./-]+(:[0-9-]+)?$' || true)
done
assert_eq "Reference Code Pointers resolve to existing paths" "" "${BAD_POINTERS# }"

# --- README screenshots: every referenced image exists, each language has the same set ---
MISSING_IMAGES=""
for image in $(grep -oE 'docs/images/[A-Za-z0-9_-]+\.png' README.md | sort -u); do
    [ -f "$image" ] || MISSING_IMAGES+=" $image"
done
assert_eq "README images exist" "" "${MISSING_IMAGES# }"
EN_IMAGES=$(grep -oE 'docs/images/en-[a-z-]+\.png' README.md | sed 's#.*/en-##' | sort -u | tr '\n' ' ')
KO_IMAGES=$(grep -oE 'docs/images/ko-[a-z-]+\.png' README.md | sed 's#.*/ko-##' | sort -u | tr '\n' ' ')
assert_eq "README English and Korean sections show the same screenshots" "$EN_IMAGES" "$KO_IMAGES"

# --- Bilingual documents use ASCII anchors with sentinels ---
for doc in README.md CHANGELOG.md docs/architecture.md docs/onboarding.md docs/api-reference.md \
           docs/runbooks/deploy-production.md docs/decisions/ADR-001-read-only-tool-boundary.md \
           docs/runbooks/deploy-document-studio.md docs/decisions/ADR-002-separate-document-studio-stack.md \
           docs/runbooks/cloudfront-oac.md docs/decisions/ADR-003-cloudfront-oac-front-door.md; do
    if grep -qF '<a id="english"></a>' "$doc" && grep -qF '<a id="korean"></a>' "$doc"; then
        pass "Bilingual anchors: $doc"
    else
        fail "Bilingual anchors: $doc" "missing <a id=\"english\"> or <a id=\"korean\">"
    fi
done
