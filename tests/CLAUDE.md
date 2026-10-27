# tests Module

## Role
Two suites live here. `test_*.py` is the pytest suite for the Python code, IAM scope and MCP STDIO
integration. `run-all.sh` with `hooks/`, `structure/` and `fixtures/` is the shell harness that validates
the Claude Code setup (hooks, settings, commands, CLAUDE.md sections).

## Key Files
- `conftest.py` — `StubSession` (real botocore models + Stubber, no network), fixed `ACCOUNT` and `NOW`
- `test_inventory.py`, `test_network_inventory.py`, `test_config_inventory.py`, `test_retries.py` — engine behavior, limits, partial failures
- `test_mcp.py`, `test_runtime_mcp_bridge.py` — real MCP client over STDIO, bridge bounds
- `test_iam.py`, `test_investigation_iam.py` — CloudFormation IAM action allow-lists
- `test_cloudfront.py`, `test_cloudfront_deployment.py`, `test_cloudfront_verification.py` — distribution/OAC/cache behaviors in both templates, `scripts/deploy_cloudfront.py` guards and `scripts/verify_cloudfront.py` checks (no AWS calls)
- `test_bma.py`, `test_web.py`, `test_reports.py`, `test_region_migration.py`, `test_deployment_parameters.py`
- `run-all.sh` — TAP-style runner; `hooks/test-hooks.sh`, `hooks/test-secret-patterns.sh`, `structure/test-plugin-structure.sh`

## Rules
- Unit tests never call AWS or a model. Use `StubSession` / sample mode.
- Build secret-like test strings at runtime by concatenation so the secret scanner and push protection do not flag them.
- Run: `.venv/bin/python -m pytest`, `bash tests/run-all.sh`. Node tests live in `web/tests/` (`cache-control.test.js` covers static GET/HEAD cache headers).
- Studio tests live in `studio/tests/` and are not collected by `pytest` (`testpaths = ["tests"]`); commands are in `studio/CLAUDE.md`.
