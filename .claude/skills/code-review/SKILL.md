---
name: code-review
description: Review changed code in this repo with confidence-based scoring (report only >= 75). Use when asked to review a diff, a file, or changes before commit, especially changes to aws_inventory tools, IAM in infra/template.yaml, web/ routes, or report rendering.
---

# Code Review Skill

Review changed code with confidence-based scoring to filter false positives.

## Review Scope

By default, review unstaged changes from `git diff`. The user may specify different files or scope.

## Review Criteria

### Project Guidelines Compliance
- Conventions in root `CLAUDE.md` and the module `CLAUDE.md` of each changed file
- Import patterns and module boundaries (ruff `I`, ESM in `web/`)
- Exact pinned dependency versions in `pyproject.toml` and `web/package.json`

### Project-Specific Invariants (highest priority)
- Query clients use `region_name=TARGET_REGION`; STS/BMA/app S3 use `APP_REGION`; no global `AWS_REGION` change
- Every resource call passes the STS account check first
- New/changed MCP tool has matching schema, normalize allow-list, IAM action on `RuntimeRole`, `tests/test_iam.py`, `docs/api-iam.md`, regenerated `web/contract.json`
- No generic boto3 operation tool, shell MCP tool, or `ReadOnlyAccess`
- No `print()` to stdout in `aws_inventory/`
- Account IDs masked to the last 3 digits in UI and reports; no reasoning or raw `command_execution` stored or shown
- `runtime/lifecycle/server.py` and generated `webapp/static/app.js` not edited by hand

### Bug Detection
- Logic errors and null/undefined handling
- Race conditions (concurrent `/api/chat` limit, investigation leases and conditional writes)
- Security vulnerabilities (OWASP Top 10: injection, XSS in report HTML, path traversal in run IDs)
- Pagination and truncation flags that misreport completeness

### Code Quality
- Code duplication and unnecessary complexity
- Missing critical error handling (stable `{ "error": "<Code>" }` responses)
- Test coverage gaps (`tests/`, `web/tests/`)
- Accessibility issues for `web/ui/` and `webapp/static/`

## Confidence Scoring

Rate each issue 0-100:
- **0-24**: Likely false positive or pre-existing issue. Do not report.
- **25-49**: Might be real but possibly a nitpick. Do not report.
- **50-74**: Real issue but minor. Report only if critical.
- **75-89**: Verified real issue, important. Report with fix suggestion.
- **90-100**: Confirmed critical issue. Must report.

**Only report issues with confidence >= 75.**

## Output Format

For each issue:
### [CRITICAL|IMPORTANT] <issue title> (confidence: XX)
**File:** `path/to/file.ext:line`
**Issue:** Clear description of the problem
**Guideline:** Reference to CLAUDE.md rule or security standard
**Fix:** Concrete code suggestion

If no high-confidence issues found, confirm code meets standards with brief summary.
