---
description: Run code review on current changes with confidence-based filtering
allowed-tools: Read, Glob, Grep, Bash(git diff:*), Bash(git log:*), Bash(git status:*)
---

# Code Review

Review the current code changes using confidence-based scoring.

## Step 1: Get Changes

Determine the scope of review:

- If $ARGUMENTS specifies files, review those files
- Otherwise, review unstaged changes: `git diff`
- If no unstaged changes, review staged changes: `git diff --cached`

## Step 2: Review

For each changed file, apply the code-review skill criteria (`.claude/skills/code-review/SKILL.md`):
- Project guidelines compliance (root `CLAUDE.md` + the module `CLAUDE.md` of the file)
- Project invariants: region separation, STS account check, read-only tool boundary, account-ID masking, no reasoning output
- Cross-file consistency: tool changes vs `infra/template.yaml` RuntimeRole, `tests/test_iam.py`, `docs/api-iam.md`, `web/contract.json`
- Bug detection (logic errors, security, performance)
- Code quality (duplication, complexity, test coverage)

## Step 3: Score and Filter

Rate each issue 0-100. Only report issues with confidence >= 75.

## Step 4: Output

Present findings in structured format with file paths, line numbers, and fix suggestions.
If no high-confidence issues, confirm code meets standards.

## Error Recovery

### If no changes found (Step 1)
No diff output means nothing to review. Inform the user:
- Check if changes are committed: `git log -1 --oneline`
- Check if on the right branch: `git branch --show-current`
- Suggest specifying files directly: `/review path/to/file`

### If CLAUDE.md is missing or empty (Step 2)
Cannot evaluate project guidelines without CLAUDE.md. Suggest:
- Run `/init-project` to generate CLAUDE.md
- Or create a minimal CLAUDE.md with conventions section

### If diff is too large (>500 lines)
Focus on high-risk files first:
1. IAM and infrastructure (`infra/*.yaml`, `runtime/Dockerfile`)
2. Tool boundary and auth (`aws_inventory/`, `web/server.js`, `web/investigation-routes.js`, `.claude/hooks/`)
3. Other logic changes
4. Documentation changes (lower priority)
