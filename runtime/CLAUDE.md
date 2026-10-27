# runtime Module

## Role
AgentCore Runtime V2 container (ARM64, HTTP protocol, port 8080). Runs the official BMA lifecycle server,
which starts `codex exec-server` so BMA can attach the local STDIO MCP, plus an IAM-protected
HTTP → STDIO MCP bridge for the optional Converse path.

## Key Files
- `Dockerfile` — `python:3.12-slim`, uid 1000 `app`, copies `aws_inventory/` and `skills/` into `/opt/bma`
- `lifecycle/server.py` — byte-identical upstream `@aws/agentcore` 1.0.0 file (provenance and SHA-256 in `UPSTREAM.md`)
- `mcp_bridge.py` — wraps the lifecycle handler: `/ping` health, bounded `/invocations` body → MCP over STDIO
- `requirements.txt` — container Python deps
- `bin/` — Codex 0.164.0 Linux ARM64 binary + `manifest.json`, placed by `scripts/prepare_runtime.py` (gitignored)
- `LICENSE-AGENTCORE` — Apache 2.0 license of the upstream lifecycle server

## Rules
- Never modify `lifecycle/server.py`; extend behavior in `mcp_bridge.py` instead.
- Build from the repo root: `docker build --platform linux/arm64 -f runtime/Dockerfile -t bma-seoul-runtime:<version> .`
- `.dockerignore` excludes `**/CLAUDE.md`, `.claude`, tests and docs; keep the image limited to runtime files.
- Verify a new image with `.venv/bin/python scripts/check_runtime.py` (network disabled; checks uid, Codex version, 4 Skills, `/ping`).
- Push with a new immutable ECR tag and deploy by digest.
