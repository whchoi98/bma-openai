# Project Context

## Overview
AI-Powered AWS Operations Desk (`bma-seoul-inventory` 0.1.0). Natural-language questions go to
Bedrock Managed Agents (BMA, Mantle model `openai.gpt-6-luna`), which call a read-only Python STDIO MCP
server inside an AgentCore Runtime V2 container. The app, BMA, Runtime and result storage run in
**`us-east-1`**; the only query target is the same account's **`ap-northeast-2`** (Seoul).
24 MCP tools, 4 Skills, 13 service categories. Live deployment record: `docs/aws-deployment.md`.

## Tech Stack
- **Python 3.12** — `boto3` 1.43.118, `mcp` 1.30.0, `fastapi` 0.162.0, `uvicorn`, `httpx`; dev: `pytest` 9.1.1, `ruff` 0.17.2, `cfn-lint`
- **Node.js 24** (ESM) — AWS SDK v3 (`client-bedrock-agentcore`, `client-bedrock-runtime`, `client-lambda`, `client-s3`, `client-sts`), React 19.3.1, `react-markdown` 10.1.0 + `remark-gfm` 4.0.1, `docx`, `pptxgenjs`, `esbuild`
- **AWS** — Lambda Web Functions (Node.js 24 only), AgentCore Runtime V2 (ARM64 container, HTTP protocol), BMA/Mantle, S3, ECR, IAM, CloudFormation
- **Runtime image** — `python:3.12-slim`, Codex 0.164.0 Linux ARM64 binary, official BMA lifecycle server (`@aws/agentcore` 1.0.0)

## Project Structure
```
aws_inventory/  - MCP server + read-only Seoul inventory engine (copied into the Runtime image)
skills/         - 4 BMA Skills (SKILL.md); /opt/bma/skills is the BMA capability directory
runtime/        - Dockerfile, unmodified upstream lifecycle server, HTTP->STDIO MCP bridge
web/            - Deployed Node.js 24 Web Function: BMA/Converse clients, SSE server, reports, investigations
web/ui/         - React answer/history/investigation components bundled by web/build-ui.mjs
webapp/         - Python local reference app (FastAPI); webapp/static/ is the shared UI shipped in the ZIP
infra/          - CloudFormation: bootstrap.yaml (ECR + code bucket), template.yaml (roles, Runtime, Web Function, worker, S3)
scripts/        - Preflight, build, deploy, live smoke and post-deploy verification scripts
tests/          - pytest suite (Stubber, MCP STDIO, IAM scope) + tests/run-all.sh harness tests
web/tests/      - node --test suite (HTTP/SSE, investigations, reports, markdown)
docs/           - Design, deployment, verification, data scope; architecture.md, reference/, runbooks/, decisions/
artifacts/      - Local build/verification evidence (gitignored; contains deployment secrets)
.claude/        - Claude settings, hooks, skills, commands, agents
```

## Conventions
- **Two regions, never mixed.** Do not set `AWS_REGION` to Seoul. Query clients pass `region_name=TARGET_REGION`; STS, BMA signing and app S3 pass `APP_REGION` explicitly.
- **Read-only boundary is code + IAM, not prompts.** A new tool needs: schema in `aws_inventory/schema.py`, handler + input validation in the engine, field allow-list in `normalize.py`, the exact IAM actions on `RuntimeRole` in `infra/template.yaml`, `tests/test_iam.py`, and a row in `docs/api-iam.md`. Never add generic boto3-operation tools, shell/command MCP tools, or `ReadOnlyAccess`.
- **Account check before every resource call.** The MCP verifies STS against `EXPECTED_ACCOUNT_ID` each time and returns `account_mismatch` without calling resource APIs.
- **MCP stdout is JSON-RPC only.** Never `print()` in `aws_inventory/`; log to stderr.
- **Regenerate contracts after Python changes.** `web/contract.json` and `web/sample-data.json` are generated from `TOOL_SCHEMAS`, Skills (with SHA-256) and sample fixtures: run `.venv/bin/python scripts/export_web_contract.py`.
- **Do not edit `runtime/lifecycle/server.py`.** It is the byte-identical upstream file (SHA-256 in `runtime/UPSTREAM.md`) and is excluded from ruff.
- **Nothing but UI assets in `webapp/static/`** — `scripts/build_web.py` zips that whole tree into the Web Function.
- **Privacy rules:** UI and all report formats show only the last 3 digits of account IDs (STS comparisons and S3 evidence keep 12 digits). Never store or display reasoning, analysis messages or raw `command_execution` output.
- **No AI attribution in git history.** Never add `Co-Authored-By` trailers or "Generated with" lines to commits or PRs. Enforced by `attribution` in `.claude/settings.json` and the `commit-msg` hook from `scripts/install-hooks.sh`.
- **Pinned versions.** Python deps use `==`, `web/package.json` uses exact versions. Keep it that way.
- **Style.** Python: ruff `E4,E7,E9,F,I`, line length 110. JS: ESM, `node:test`. Korean user-facing docs use 경어체 or the existing 평서체 of the file being edited.

## Key Commands
```bash
# Setup
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e '.[dev]'
npm ci --ignore-scripts --prefix web

# Test and lint (no AWS calls)
.venv/bin/python -m pytest
npm test --prefix web
.venv/bin/ruff check .
bash tests/run-all.sh                     # Claude harness tests (hooks, structure)

# Local sample mode (no AWS API or model calls)
npm run build --prefix web && DATA_MODE=sample node web/index.js   # http://127.0.0.1:3000
DATA_MODE=sample .venv/bin/python -m aws_inventory.mcp_server

# Build artifacts
.venv/bin/python scripts/export_web_contract.py
.venv/bin/python scripts/prepare_runtime.py
docker build --platform linux/arm64 -f runtime/Dockerfile -t bma-seoul-runtime:0.1.0 .
.venv/bin/python scripts/build_web.py

# Live AWS (ask the user first: real account, real cost)
.venv/bin/python scripts/preflight.py --list-models
.venv/bin/python scripts/live_smoke.py
```
Deployment: follow `docs/runbooks/deploy-production.md`. Every deploy uses a new immutable ECR tag, the new ZIP's S3 VersionId and the image digest; never `--disable-rollback` on Web Revision updates.

## Error Handling
- Tool results always carry `status` (`ok`, `empty`, `access_denied`, `unsupported_service`, `api_error`, `partial`, `account_mismatch`, `invalid_input`), `truncated`, `pagination_complete` and `errors`. Return these instead of raising, and never forward raw AWS error messages.
- HTTP errors return `{ "error": "<Code>" }` with stable codes (see `docs/api-reference.md`).

---

## Auto-Sync Rules

Rules below are applied automatically after Plan mode exit and on major code changes.

### Post-Plan Mode Actions
After exiting Plan mode (`/plan`), before starting implementation:

1. **Architecture decision made** -> Update `docs/architecture.md`
2. **Technical choice/trade-off made** -> Create `docs/decisions/ADR-NNN-title.md`
3. **New module added** -> Create `CLAUDE.md` in that module directory
4. **Operational procedure defined** -> Create runbook in `docs/runbooks/`
5. **Changes needed in this file** -> Update relevant sections above

### Code Change Sync Rules
- New top-level source directory -> Must create `CLAUDE.md` alongside (never inside `webapp/static/`)
- MCP tool added/changed -> Update `aws_inventory/CLAUDE.md`, `docs/api-iam.md`, `infra/template.yaml` RuntimeRole, then re-export `web/contract.json`
- HTTP endpoint added/changed in `web/server.js` or `web/investigation-routes.js` -> Update `web/CLAUDE.md` and `docs/api-reference.md`
- Infrastructure changed (`infra/*.yaml`, `runtime/Dockerfile`) -> Update `docs/architecture.md` Infrastructure section and `docs/runbooks/deploy-production.md`
- Live deployment changed -> Update `docs/aws-deployment.md` with the verified values

### ADR Numbering
Find the highest number in `docs/decisions/ADR-*.md` and increment by 1.
Format: `ADR-NNN-concise-title.md`

## Implementation References
<!-- AUTO-MANAGED:references -->
Layer-by-layer implementation guides in `docs/reference/`. See [INDEX](docs/reference/INDEX.md).
- [Infrastructure](docs/reference/infrastructure.md)
- [API](docs/reference/api.md)
- [IaC](docs/reference/iac.md)
- [Frontend](docs/reference/frontend.md)
- [UI](docs/reference/ui.md)
- [Security](docs/reference/security.md)
- [Agent · LLM](docs/reference/agent-llm.md)
<!-- /AUTO-MANAGED -->
