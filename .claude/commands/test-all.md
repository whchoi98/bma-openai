---
description: Execute the full test suite (pytest, node:test, ruff, harness) and report results
allowed-tools: Read, Glob, Bash(.venv/bin/python -m pytest:*), Bash(npm test --prefix web:*), Bash(.venv/bin/ruff check:*), Bash(bash tests/run-all.sh:*), Bash(.venv/bin/cfn-lint:*)
---

# Test All

Execute the full test suite for this project. None of these commands call AWS or a model.

## Step 1: Check Environment

- `.venv/bin/python` exists (otherwise: `bash scripts/setup.sh`)
- `web/node_modules` exists (otherwise: `npm ci --ignore-scripts --prefix web`)

## Step 2: Run Tests

Run each suite and keep going if one fails, so the report covers all of them:

```bash
# Python unit and integration tests (Stubber, MCP STDIO, IAM scope)
.venv/bin/python -m pytest

# Node.js Web Function tests
npm test --prefix web

# Lint
.venv/bin/ruff check .

# CloudFormation lint
.venv/bin/cfn-lint infra/bootstrap.yaml infra/template.yaml

# Claude harness tests (hooks, settings, structure)
bash tests/run-all.sh
```

If $ARGUMENTS is given, run only the matching suite (`python`, `node`, `lint`, `cfn`, `harness`)
or pass it through as a pytest `-k` expression.

## Step 3: Report

Present:
- Total tests run, passed, failed, skipped per suite
- Failed test details with file paths and error messages
- Suggest fixes for failing tests if the cause is apparent

## Error Recovery

### If test runner itself fails
```bash
bash -n tests/run-all.sh          # Check syntax
ls -la tests/**/*.sh              # Check permissions
chmod +x tests/**/*.sh            # Fix permissions
```

### Common failure categories and fixes

| Failure Pattern | Likely Cause | Fix |
|---|---|---|
| `web/contract.json` mismatch | Python schema, Skills or samples changed | `.venv/bin/python scripts/export_web_contract.py` |
| `webapp/static/app.js` stale | UI source changed without rebuild | `npm run build --prefix web` |
| IAM test failure | Tool added without RuntimeRole action | Update `infra/template.yaml` and `docs/api-iam.md` |
| cfn-lint exit 4 with only `W3037` on `bedrock-mantle:*` actions | cfn-lint's IAM spec predates the BMA actions (warnings, not errors) | Report as known warnings; treat any `E` code as a failure |
| "invalid JSON" | Malformed settings or manifest | `python3 -m json.tool <file>` |
| "not executable" | Permission reset by git | `chmod +x` on affected files |
| "bash syntax error" | Bad edit in script | `bash -n <file>` to locate error |

### If many tests fail at once
Likely a structural change broke multiple assumptions:
1. `git log -1` — what was the last change?
2. `git diff HEAD~1` — what specifically changed?
3. Fix the root cause, not individual tests
