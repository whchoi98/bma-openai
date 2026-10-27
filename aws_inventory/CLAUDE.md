# aws_inventory Module

## Role
Read-only, account-bound Seoul (`ap-northeast-2`) inventory exposed as 24 MCP tools over STDIO.
BMA starts it inside the Runtime container via `agent.tools[].transport.type=stdio`; the Converse path
reaches the same server through `runtime/mcp_bridge.py`. Copied into the image by `runtime/Dockerfile`.

## Key Files
- `mcp_server.py` — official MCP SDK STDIO server; `create_server()` registers tools, `main()` is the `aws-inventory-mcp` entry point
- `schema.py` — `TOOL_SCHEMAS`: strict pydantic argument models (`extra="forbid"`, ID patterns)
- `engine.py` — `AwsInventory.invoke()` dispatch, `_verify_account()` STS check, bounded `paginate()`, `Observation` result envelope
- `config.py` — `Settings` (regions, limits, mode) and `SUPPORTED_SERVICES`
- `normalize.py` — field allow-lists; drops credentials, env vars, endpoints, tags, raw error text
- `metrics.py` — CloudWatch windows (max 6 h, last 7 days, 300 s buckets, max 1,440 points)
- `network_inventory.py`, `config_inventory.py` — VPC/EBS/ECR and S3/DynamoDB/ElastiCache/OpenSearch/MSK reads
- `sample.py`, `network_samples.py`, `config_samples.py` — deterministic fixtures for `DATA_MODE=sample`

## Rules
- Never write to stdout (JSON-RPC channel). Use stderr logging.
- Every resource call goes through `AwsInventory.call()` after `_verify_account()`; mismatch returns `account_mismatch` with no resource API call.
- Clients are created with `region_name=TARGET_REGION` only. Do not read `AWS_REGION`.
- Respect `MAX_RESOURCES` (≤100), `MAX_PAGES` (≤10), and mark `truncated` / `pagination_complete` honestly.
- Adding or changing a tool: update `schema.py`, engine handler, `normalize.py`, sample fixture, `infra/template.yaml` RuntimeRole actions, `tests/test_iam.py`, `docs/api-iam.md`, then run `.venv/bin/python scripts/export_web_contract.py`.
- Tests use `tests/conftest.py` `StubSession` (botocore Stubber); no network in unit tests.
