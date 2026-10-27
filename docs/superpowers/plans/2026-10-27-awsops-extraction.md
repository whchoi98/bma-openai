# AWSops extraction implementation plan

> **For agentic workers:** Use subagent-driven-development for the independent backend tasks and a final integrated review. The user approved priorities 1, 2, 3 and confirmed `/home/ec2-user/my-project/awsops` as the extraction source.

**Goal:** Add bounded VPC/EBS/ECR and additional configuration inventory, observed network relationships, configuration security findings, account-scoped report history, and redacted DOCX/PPTX exports.

**Architecture:** Retain the existing Node Web Function, Luna Converse/BMA selection, Python STDIO MCP, and three-role IAM split. Extract relevant query semantics, graph relationships, Markdown/export helpers from the original awsops source; do not proxy its generic SQL, CLI, credential config, or automated remediation. Store history indexes in the existing application S3 bucket.

**Tech stack:** Python 3.12/boto3/Pydantic/Stubber; Node.js 24/React/remark-gfm; SVG; docx/pptxgenjs; CloudFormation.

**Spec:** User-approved priorities from `docs/awsops-v2-integration-review.md`, superseded only as to extraction source: use `../awsops`, not `../awsops_v2`.

## Global constraints

- APP_REGION=us-west-2, TARGET_REGION=ap-northeast-2, EXPECTED_ACCOUNT_ID verified via STS before every MCP invocation.
- Model remains global.openai.gpt-6-luna. Preserve BMA alternative, SSE, Korean/English, dark mode, NanumSquare OTF Bold, HTML preview and masking.
- Source repository is read-only. Record original file hashes and extraction/adaptation notes.
- No mutations of queried resources, no arbitrary AWS/SQL/CLI operation tools, no internal DB/object/item data access, no logs/cost/Kubernetes extensions in this release.
- Query caps and bounded retries remain enforced. Topology only links observed IDs; configuration findings never imply application health or compliance certification.
- Use official SDK/API and service authorization documents for every new action; never attach managed ReadOnlyAccess. Apply Seoul conditions only to compatible resource-read actions.
- Keep full identity only in internal validation/evidence; public display and all exports redact the account except its final 3 digits.
- No Git repository is present in the target workspace. Work in the user-authorized existing workspace with non-overlapping module ownership; do not initialize Git or commit/push.

## Interfaces and ownership

### Task 1: network/storage/container registry reads
Files: `aws_inventory/network_inventory.py`, `aws_inventory/network_samples.py`, `tests/test_network_inventory.py`, `docs/extraction-network.md`.
Expose `TOOL_SCHEMAS`, `DATA_FIELDS`, and `handlers(engine) -> dict[str, callable]` from network_inventory. Handler signature is `(obs, **validated_args)` and every SDK call uses the parent engine's `call`, `client`, and bounded pagination. Do not edit shared engine/schema/config or UI files.
Tools: `list_vpcs`, `get_vpc_topology(vpc_id)`, `list_security_groups(vpc_id)`, `list_ebs_volumes`, `list_ecr_repositories`.
Topology data rows use `kind`, `id`, `vpc_id`, optional `subnet_id`, `subnet_ids`. Respect total max_resources and explicitly record unqueried/truncated kinds. SG rows have bounded `ingress_rules`, an `ingress_complete` boolean and `security_checks`.
Security checks use `{id, status: pass|fail|unknown, severity: high|medium|info}`; findings are configuration facts only.
Sample adapter interface: `response(service, operation, params)` returns a boto-style fixed response, raises KeyError when not owned. No real AWS in tests.
- [x] Read original network MCP/query/topology source and official APIs/actions.
- [x] Write Stubber tests for region, account mismatch, pagination, denied/empty/partial, sanitization and SG rules.
- [x] Implement the fixed read functions and sample responses.
- [x] Run scoped tests; record provenance and exact action matrix.

### Task 2: additional service configuration and security data
Files: `aws_inventory/config_inventory.py`, `aws_inventory/config_samples.py`, `tests/test_config_inventory.py`, `docs/extraction-config.md`.
Same interfaces as Task 1; no shared file edits. Services include S3, DynamoDB, ElastiCache, OpenSearch, MSK, with exact explicit SDK operations.
Tools: `list_s3_buckets`, `get_s3_bucket_configuration(bucket)`, `list_dynamodb_tables`, `get_dynamodb_table_configuration(table_name)`, `list_elasticache_clusters`, `list_opensearch_domains`, `get_opensearch_domain_configuration(domain_name)`, `list_msk_clusters`.
Lists may return IDs only when configuration requires a separate API; do not invent healthy states. S3 discovery must be explicitly scoped to Seoul and same owner. Config reads set ExpectedBucketOwner where supported. Return only allowlisted fields, never endpoint/credentials/policies/raw objects or table items.
Security fields: encryption/public access/versioning/PITR/auth-at-rest flags when actually returned; unknown stays unknown. `security_checks` follows Task 1's schema.
- [x] Read original source MCP/query helpers and official APIs/actions.
- [x] Write Stubber tests covering all operations and sensitive-field removal.
- [x] Implement bounded reads and sample adapter.
- [x] Run scoped tests; record source hashes and permission matrix.

### Task 3: report history and Office exports
Files: `web/stores.js`, `web/history.js`, `web/office-reports.js`, `web/history-migrate.js`, `web/tests/history.test.js`, `web/tests/office-reports.test.js`, `docs/extraction-reports.md`.
Do not edit server/UI/package.json/lock/IAM. Report exact dependency versions required to the coordinator.
`MemoryStore(settings)` and `S3Store(settings)` retain get/put and add `list({limit,cursor})`. Return `{runs, next_cursor, complete}`. Bound limit to 1..20. Store history indexes under a fixed `history/<account>/<target-region>/` prefix with reverse timestamp keys for newest-first pagination. Never silently turn failures into empty history. Include redacted summary scope and query coverage, not full evidence.
`history.js` exposes helpers for validating a record against configured account/region and producing list summaries. A migration CLI backfills at most 200 existing `runs/` records after verifying STS account, without editing/deleting originals.
`renderOfficeReport(record, format, {accountIds}) -> Promise<Buffer>` for docx/pptx; `OFFICE_MIME` provides exact MIME types. Extract/adapt original report-docx/report-pptx helpers, use redaction before writing Office XML, cap output size/slides and clearly label any presentation truncation. No model/API calls for export. Preserve UTC/KST, scope, errors and evidence.
- [x] Inspect original Office/history source and record provenance.
- [x] Write history pagination/scope/failure tests and Office ZIP/XML redaction/content tests.
- [x] Implement bounded account-specific history and exporters.
- [x] Run tests and provide the integration signatures/dependencies.

### Task 4: coordinator integration
Files: shared engine/schema/config/sample, evidence allowlists, Skills, `web/server.js`, `web/runners.js`, `web/converse.js`, UI, styles, IAM and docs.
- [x] Register Task 1/2 schemas and handlers; add explicit SDK client names separately from display service names.
- [x] Extend evidence normalization for bounded topology/security fields; keep untrusted nested fields out.
- [x] Add S3 history ListBucket and index Get/Put only for the fixed app bucket/prefix. Add only documented new Runtime read actions.
- [x] Add authenticated GET `/api/runs?limit=&cursor=` and `/api/runs/:id`, binary report formats, and bounded history migration.
- [x] Add localized history list/load controls and DOCX/PPTX buttons. Loading a report must not rerun queries.
- [x] Extract relationship semantics from the original topology page into an accessible SVG graph. Draw only returned IDs, show coverage/truncation, and preserve masking.
- [x] Show deterministic security-check results with pass/fail/unknown, never app-health claims. Add aws-security-posture Skill and update service selection instructions.
- [x] Regenerate contract/sample fixtures and verify both live and sample paths expose the full supported catalog.

### Task 5: validation and deployment
- [x] Run Python Stubber and Node regression tests; inspect generated DOCX/PPTX ZIP XML and browser behavior in both languages/themes.
- [x] Build/probe the exact Runtime container and Web ZIP, ensure no secret inclusion.
- [x] Review integrated code, IAM and source-provenance records.
- [x] Deploy the existing stack and run bounded live queries (few resources, no data-plane access) including new reads, topology, security, history/reload and all export formats.
- [x] Backfill bounded existing history; document observed successes, empty/denied/partial results without invention.
- [x] Update deployment/evidence docs and source archive; keep awsops source tree untouched.
