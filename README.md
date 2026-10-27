# AI-Powered AWS Operations Desk

[![License](https://img.shields.io/badge/License-MIT--0-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-0.1.0-green.svg)](pyproject.toml)
<a href="#english"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English"></a>
<a href="#korean"><img src="https://img.shields.io/badge/lang-한국어-red.svg" alt="Korean"></a>

Connect natural-language questions to read-only Seoul AWS inventory through Bedrock Managed Agents | 자연어 질문을 BMA를 통해 서울 리전의 읽기 전용 AWS 조회로 연결합니다

---

<a id="english"></a>

# English

## Overview

AI-Powered AWS Operations Desk connects natural-language questions to Bedrock Managed Agents (BMA) Skills,
Python MCP tools, and real AWS control API reads. The app, **BMA, AgentCore Runtime V2, and result storage run in
`us-east-1`**; the query target is **`ap-northeast-2`** in the same account. The model is Mantle's
**`openai.gpt-6-luna`**.

The previous Oregon deployment of this project was deleted and migrated to US East (N. Virginia).
Check the actual deployment status and verification records in the [deployment report](docs/aws-deployment.md).

The project provides three scopes extracted from the original `/home/ec2-user/my-project/awsops`:
VPC/EBS/ECR with relationship diagrams, report history with DOCX/PPTX, and configuration reads and
security-setting checks for S3/DynamoDB/ElastiCache/OpenSearch/MSK. It currently supports
**24 MCP tools, 4 Skills, and 13 service categories**.

The repository also contains **[AI Document Studio](#ai-document-studio)** (`studio/`), a separate demo for
office workers that turns a spreadsheet or notes into charts, diagrams, and editable PPTX/DOCX with
`openai.gpt-6.1-sol`. It runs on its own Web Function, document-only Runtime, and stacks without AWS resource-query permissions.

Both apps are served through CloudFront with Lambda Web OAC. Public HTML and
static assets can be served from Seoul edge locations; API/SSE/private documents
are not cached. Model work remains in us-east-1. See the
[CloudFront runbook](docs/runbooks/cloudfront-oac.md), the
[CloudFront deployment and verification record](docs/cloudfront-deployment.md), and current
[Desk](docs/aws-deployment.md) / [Studio](docs/document-studio.md) addresses.

![Operations Desk main screen: account and region card, supported services, question form, and a completed answer](docs/images/en-overview.png)

## Features

- **Read-only Seoul inventory** — Query `ap-northeast-2` control APIs through 24 registered MCP tools only after STS confirms the expected account; no arbitrary-command or generic boto3 operation tools exist.
- **Streaming BMA answers** — Forward public `agent.session.turn.output_text.delta` text over SSE and render it with react-markdown 10.1.0 + remark-gfm 4.0.1, showing query steps, elapsed time, and tool records without internal reasoning.
- **Reports with account masking** — Render saved results as Markdown/HTML/DOCX/PPTX reports that show only the last 3 digits of the account ID, without re-querying the model or resources.
- **Operations investigations** — Send follow-up questions to the same BMA session, recover the same run after reconnecting, and track four versioned operating procedures.
- **Relationship and security views** — Connect only actually observed resources in relationship diagrams and classify security checks as met, needs review, or unverified.
- **CloudFront front door** — Serve each app from its own CloudFront distribution with Lambda Web OAC; the regional origin accepts only that distribution (`IamAuth`), public HTML and static files are cached at Seoul edges, and API, SSE, uploads, and private downloads are never cached.
- **AI Document Studio** — Turn one XLSX/CSV/TXT/MD file or pasted notes into charts, diagrams, and editable PPTX/DOCX in three styles, with real progress phases and a sandboxed preview; numbers come from code, not the model.

### Screenshots

Captured from sample mode (`DATA_MODE=sample`) with fixed synthetic data, so no AWS API or model was called
and no real resource appears. Regenerate them with `.venv/bin/python scripts/capture_screenshots.py`.

<table>
  <tr>
    <td width="50%" valign="top"><img src="docs/images/en-answer.png" alt="Answer panel with a Markdown result and report download buttons"><br><sub><b>Streaming answer</b> — Markdown rendering of public text deltas with MD/HTML/DOCX/PPTX downloads</sub></td>
    <td width="50%" valign="top"><img src="docs/images/en-trace.png" alt="Tool activity table with duration, result count, status, and AWS API calls"><br><sub><b>Tool activity</b> — every MCP call with region, duration, result count, and the AWS APIs it used</sub></td>
  </tr>
  <tr>
    <td width="50%" valign="top"><img src="docs/images/en-topology.png" alt="Resource relationship graph of a VPC with subnets, gateways, endpoints, and security groups"><br><sub><b>Resource relationships</b> — only observed configuration references, with the selected node's normalized fields</sub></td>
    <td width="50%" valign="top"><img src="docs/images/en-security.png" alt="Security configuration check table with meets and needs-review results"><br><sub><b>Security configuration checks</b> — security groups, RDS, and EBS settings classified as meets, needs review, or unverified</sub></td>
  </tr>
  <tr>
    <td width="50%" valign="top"><img src="docs/images/en-report-preview.png" alt="HTML report preview dialog with service status table"><br><sub><b>HTML report preview</b> — the saved report in a sandboxed iframe; opening it never re-queries AWS or the model</sub></td>
    <td width="50%" valign="top"><img src="docs/images/en-history.png" alt="Report history list with prompts, services, and status"><br><sub><b>Report history</b> — saved runs with their services and status, loaded without a new query</sub></td>
  </tr>
  <tr>
    <td width="50%" valign="top"><img src="docs/images/en-investigation.png" alt="Operations investigation with procedure steps, follow-up form, and tool activity"><br><sub><b>Operations investigation</b> — versioned procedure, per-step status, follow-up questions in the same session</sub></td>
    <td width="50%" valign="top"><img src="docs/images/en-mobile.png" alt="Mobile layout at 390 pixels wide"><br><sub><b>Mobile layout</b> — 390 px viewport without horizontal scrolling</sub></td>
  </tr>
  <tr>
    <td colspan="2"><img src="docs/images/en-dark.png" alt="Dark mode with an operations investigation result"><br><sub><b>Dark mode and English UI</b> — theme and language switch from the top bar</sub></td>
  </tr>
</table>

### AI Document Studio

A separate demo in [`studio/`](studio/) for non-developers. Upload one XLSX/CSV/TXT/MD file (up to 5 MiB)
or paste notes, describe the result in plain language, and pick PowerPoint, Word, chart, and diagram
outputs in the business report, AWS Operations Desk, or presentation style. BMA (`openai.gpt-6.1-sol`)
writes the structure and wording, while six bounded document MCP tools aggregate the real values and
render PNG/SVG, editable PPTX/DOCX, and an HTML content preview. Downloads are authenticated, and files
expire after 7 days. Usage, limits, and live verification (Korean): [document-studio.md](docs/document-studio.md);
deployment: [runbook](docs/runbooks/deploy-document-studio.md).

The screenshots come from a local fixture: the real Studio UI and HTTP routes serve files rendered by the
real Python renderers from [`studio/examples/`](studio/examples/). Only the answer text is fixed, and no AWS API or
model was called. Regenerate them with `.venv/bin/python scripts/capture_screenshots.py studio`.

<table>
  <tr>
    <td colspan="3"><img src="docs/images/en-studio-result.png" alt="AI Document Studio with a finished job: answer summary, five files, and a document preview with a monthly revenue chart"><br><sub><b>Finished documents</b> — chart PNG/SVG, PPTX, DOCX, and the HTML content preview with the chart aggregated from the uploaded spreadsheet</sub></td>
  </tr>
  <tr>
    <td width="33%" valign="top"><img src="docs/images/en-studio-brief.png" alt="Brief form with an uploaded spreadsheet, request, output choices, and document styles"><br><sub><b>Brief</b> — one file or notes, a plain-language request, outputs, and one of three styles</sub></td>
    <td width="33%" valign="top"><img src="docs/images/en-studio-progress.png" alt="Progress panel with completed phases, current phase, and elapsed time"><br><sub><b>Progress</b> — real job phases and elapsed time, no invented percentages</sub></td>
    <td width="33%" valign="top"><img src="docs/images/en-studio-diagram.png" alt="Earlier job showing a workflow diagram file in the AWS Operations Desk style"><br><sub><b>Diagram output</b> — notes turned into a workflow diagram in the AWS Operations Desk style</sub></td>
  </tr>
</table>

## Architecture

```mermaid
flowchart LR
  U["Browser"] --> CF["CloudFront / OAC"]
  CF --> W["Lambda Web Function<br/>us-east-1 / IamAuth"]
  W --> B["BMA / Mantle<br/>openai.gpt-6-luna<br/>us-east-1"]
  B --> R["AgentCore Runtime V2<br/>us-east-1"]
  K["4 Skills"] --> R
  R --> M["Python STDIO MCP"]
  M --> S["Seoul AWS control APIs<br/>ap-northeast-2"]
  S --> M
  B -->|"public text delta"| W
  W -->|"SSE / Markdown"| CF
  CF --> U
  W --> O["Normalized app results<br/>S3 / us-east-1"]
```

BMA reads the Skills in the Runtime and runs MCP with `agent.tools[].transport.type=stdio`.
The Runtime protocol is HTTP and the platform is V2; the official lifecycle server is unchanged.
The Web Function verifies the deployment account with STS and then creates a BMA session. MCP separately
verifies the Runtime's actual account and calls Seoul resource APIs only when the accounts match.

**Information queried in Seoul and passed to the model is analyzed by BMA in US East (N. Virginia).**
A Seoul query does not mean processing only within Seoul. Detailed retention policy and networking are in
[Data Processing and Scope](docs/data-and-scope.md). See the [architecture document](docs/architecture.md)
for the full layered architecture.

## Prerequisites

- Node.js 24 (`engines.node >= 24`; the Web Functions runtime supports Node.js 24 only)
- Python 3.12 and `uv`
- Docker with `linux/arm64` build support (Runtime image)
- AWS CLI v2 and `jq` (deployment)
- Official Codex 0.164.0 Linux ARM64 binary (Runtime build; located by `scripts/prepare_runtime.py`)
- AWS credentials for the target account (live mode, live verification, and deployment only)

## Installation

```bash
# Clone the repository
git clone https://github.com/whchoi98/bma-openai.git
cd bma-openai

# Install Node.js dependencies and build the UI
npm ci --ignore-scripts --prefix web
npm run build --prefix web

# Create the Python environment and install development dependencies
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[dev]'

# Optional: AI Document Studio environment and package link
uv venv --python 3.12 .studio-venv
uv pip install --python .studio-venv/bin/python -r studio/requirements.txt
ln -s ../web/node_modules studio/node_modules
```

## Usage

Run the sample screen on Node.js 24. Sample mode does not call AWS APIs or the model.

```bash
DATA_MODE=sample node web/index.js
```

Open `http://127.0.0.1:3000` in the browser. `DATA_MODE`, the account, and the regions are server settings and
cannot be changed through questions or browser input. The sample account and observation time are fixed fixtures.

Run the MCP server in sample mode:

```bash
DATA_MODE=sample .venv/bin/python -m aws_inventory.mcp_server
```

The MCP server's stdout is reserved for JSON-RPC. The real MCP client connection is verified by `tests/test_mcp.py`.

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `APP_REGION` | Region for the app, BMA, Runtime, and result storage | `us-east-1` |
| `TARGET_REGION` | Region queried for AWS resources | `ap-northeast-2` |
| `EXPECTED_ACCOUNT_ID` | Account confirmed with STS at deployment; CloudFormation injects it with `AWS::AccountId` | (empty) |
| `DATA_MODE` | `live` or `sample`; missing settings are rejected at startup | `live` |
| `BMA_MODEL` | Model confirmed with the us-east-1 Mantle model list and BMA session creation | `openai.gpt-6-luna` |
| `AGENT_BACKEND` | Current backend `bma`; the selectable alternative is `converse` | `bma` |
| `CONVERSE_MODEL` | Designated inference profile for the Converse path | `global.openai.gpt-6-luna` |
| `MODEL_PROCESSING_SCOPE` | Runtime data-flow label: `global` for Converse, `app_region` for BMA; set in IaC | `app_region` |
| `BMA_RUNTIME_ARN` | us-east-1 Runtime ARN in the same account | (empty) |
| `BMA_SESSION_ROLE_ARN` | Designated BMA session role ARN in the same account | (empty) |
| `INVESTIGATION_WORKER_ARN` | Designated investigation worker Lambda ARN in the same account and us-east-1 | (empty) |
| `APP_STATE_BUCKET` | us-east-1 bucket that stores app results | (empty) |
| `APP_ACCESS_TOKEN` | Live-mode access key, at least 32 characters; never placed in source or the browser bundle | (empty) |
| `MAX_RESOURCES` | Maximum resources per tool; the value can only be lowered | `100` |
| `MAX_PAGES` | Maximum pages per tool | `10` |
| `MAX_METRIC_HOURS` | Maximum hours per metric query, within the last 7 days | `6` |
| `MAX_DATAPOINTS` | Maximum datapoints, 300-second buckets | `1440` |
| `MAX_TURN_SECONDS` | Agent run and stream limit; the current deployment uses 300 seconds | `180` |

Do not switch all of `AWS_REGION` to Seoul. Query boto3 clients set `region_name=TARGET_REGION`, and STS,
BMA signing, and the app S3 bucket set `APP_REGION` explicitly. The `AWS_REGION` used by the official Runtime
lifecycle is US East (N. Virginia).

The Web Function has permissions to invoke BMA, AssumeRole the designated session role, and store app results;
it has no Seoul query permissions. The session role uses only the selected model and the designated Runtime.
Query permissions exist only on the Runtime role. The operations investigation worker uses only the BMA session
API and limited app state and does not query AWS resources directly. The managed `ReadOnlyAccess` policy,
an arbitrary-command MCP, and a generic boto3 operation tool were not added.

## Project Structure

```text
bma-openai/
├── .claude/              # Claude Code settings, hooks, skills, commands, and agents
├── aws_inventory/        # Account checks, fixed-region boto3 clients, 24 MCP tools, normalization and limits
├── docs/                 # Design, deployment, data scope, and investigation guides
│   ├── architecture.md   # System architecture document
│   ├── images/           # README screenshots from scripts/capture_screenshots.py
│   ├── reference/        # Layer-by-layer implementation references
│   ├── runbooks/         # Operational runbooks
│   └── decisions/        # Architecture Decision Records
├── infra/                # CloudFormation bootstrap and application stacks
├── runtime/              # Official BMA lifecycle server, HTTP-to-STDIO MCP bridge, ARM64 Dockerfile
├── scripts/              # Preflight, build, deployment, and live verification scripts
├── skills/               # 4 BMA Skills packaged into the Runtime image
├── studio/               # AI Document Studio: document MCP/renderers, Web Function, Skills, stacks, tests
├── tests/                # Python tests and the tests/run-all.sh harness suite
├── web/                  # Node.js 24 Web Function, BMA/Converse clients, reports, React answer components
└── webapp/               # Python local reference app and shared static UI
```

### Key Files

| Path | Role |
| --- | --- |
| `aws_inventory/` | Account/owner verification, fixed-region boto3 clients, 24 MCP tools, normalization and limits |
| `skills/` | Inventory, health check, and operations report Skills |
| `runtime/` | Official BMA lifecycle server, restricted HTTP-to-STDIO MCP bridge, ARM64 Dockerfile |
| `web/` | Node.js 24 BMA/Converse clients, web server, reports, React answer components |
| `webapp/static/` | Shared screen showing both regions, live/sample mode, and query records |
| `webapp/` | Python local reference HTTP app, fixed response generation, and local report writing |
| `infra/` | 4 roles, Runtime V2, Web Function, investigation worker Lambda, app S3 |
| `scripts/` | Account preflight, builds, and small-scale live queries |
| `tests/`, `web/tests/` | Stubber, MCP STDIO, HTTP/SSE, and IAM policy scope verification |
| `studio/` | AI Document Studio: input parsing, chart aggregation, Office renderers, job-bound MCP, separate Web Function, worker, and stacks |

## Testing

```bash
# Python tests (Stubber, MCP STDIO, IAM policy scope, CloudFront templates and deployer)
.venv/bin/python -m pytest

# Node.js tests (BMA/Converse clients, HTTP/SSE, cache headers, reports, investigations)
npm test --prefix web

# Lint
.venv/bin/ruff check .

# Claude Code harness tests (hooks, secret patterns, project structure)
bash tests/run-all.sh

# AI Document Studio (parsing, rendering, MCP, IAM scope, HTTP/worker)
.studio-venv/bin/python -m unittest studio.tests.test_input_data studio.tests.test_render studio.tests.test_job
.venv/bin/python -m unittest studio.tests.test_infra
node --test studio/tests/backend.test.js studio/tests/cache-control.test.js
```

## API Documentation

The Web Function serves `/health` and the `/api/*` routes: `/api/context`, `/api/chat` (SSE), `/api/runs`,
`/api/runs/{id}`, `/api/runs/{id}/report.{md|html|docx|pptx}`, `/api/procedures`, and `/api/investigations`
with its turn, event, and cancel sub-routes. When an access key is configured, `/api/*` requires
`Authorization: Bearer <APP_ACCESS_TOKEN>`; unauthenticated API requests return 401.
See the [API reference](docs/api-reference.md) for request and response details, including the separate
[AI Document Studio API](docs/api-reference.md#ai-document-studio-api) (`/api/config`, `/api/uploads`, `/api/jobs/**`).

## Contributing

1. Fork the repository
2. Create your branch (`git checkout -b feat/amazing-feature`)
3. Commit changes (`git commit -m 'feat: add amazing feature'`)
4. Push to the branch (`git push origin feat/amazing-feature`)
5. Open a Pull Request

Use [Conventional Commits](https://www.conventionalcommits.org/) for commit messages:

```bash
git commit -m "feat: add ElastiCache encryption check"
git commit -m "fix: mask account IDs split across Markdown emphasis"
git commit -m "docs: update deployment runbook"
```

## License

This project is licensed under the [MIT No Attribution (MIT-0)](LICENSE) license.
`runtime/lifecycle/server.py` is included unchanged from the official `@aws/agentcore` npm package 1.0.0 and
remains under its original Apache License 2.0 in [runtime/LICENSE-AGENTCORE](runtime/LICENSE-AGENTCORE).
See [runtime/UPSTREAM.md](runtime/UPSTREAM.md) for its source.

## Contact

- Maintainer: [WooHyung Choi (whchoi98)](https://github.com/whchoi98)
- Issues: [github.com/whchoi98/bma-openai/issues](https://github.com/whchoi98/bma-openai/issues)

## Model, UI, and Streaming

- The current configuration is `AGENT_BACKEND=bma`, `BMA_MODEL=openai.gpt-6-luna`.
  Public answers from `agent.session.turn.output_text.delta` are forwarded over SSE immediately.
- The existing `AGENT_BACKEND=converse` implementation remains as a selectable alternative.
  This path uses `global.openai.gpt-6-luna` and `ConverseStreamCommand` and displays the global processing
  scope separately. The current BMA deployment does not grant global inference permissions.
- Answers render with **react-markdown 10.1.0 + remark-gfm 4.0.1**.
  The UI shows query steps, elapsed time, and tool records; internal reasoning is neither displayed nor stored.
- The font is the local NAVER **NanumSquare OTF Bold**. The OFL license is included and no CDN is used.
- The header toggles dark mode and Korean/English and shows the actual model ID and execution/query regions.
- The UI and the Markdown/HTML/DOCX/PPTX reports show only the last 3 digits of the account ID.
  STS comparison and the original evidence in S3 keep the full account ID.
- **View HTML report** renders a saved report. Loading history, previews, and document conversion do not
  re-query the model or resources.
- Relationship diagrams connect only actually observed resources. Security configuration checks distinguish
  met, needs review, and unverified.
- **Operations investigations** send follow-up questions to the same BMA session and recover the same run after
  reconnecting. They show the versions and actual step status of four operating procedures and preserve the
  original timestamps of earlier evidence. The existing **single question** mode creates a new session for each
  question. See the [usage guide](docs/bma-investigations.md).

## Deployment Preparation

First check the deploying principal's account and the model list. Listing models is not an inference call.

```bash
.venv/bin/python scripts/preflight.py --list-models
.venv/bin/python scripts/prepare_runtime.py
docker build --platform linux/arm64 -f runtime/Dockerfile -t bma-seoul-runtime:0.1.0 .
.venv/bin/python scripts/build_web.py
```

`prepare_runtime.py` locates the officially installed **Codex 0.164.0 Linux ARM64** binary.
If it is in another location, pass `--source /path/to/codex`. The script checks the version, ELF architecture,
and exec-server options. The Web Function ZIP contains the Node.js code, its dependencies, and the static UI.
`artifacts/deployment-context.json` records the verified real account; if the account changes in a later check,
the script stops instead of overwriting the existing expected account.

The commands below reproduce the deployment. The current deployment and actual verification results are recorded
in the [AWS deployment report](docs/aws-deployment.md). For the step-by-step operational procedure, follow the
[deployment runbook](docs/runbooks/deploy-production.md).

```bash
export APP_REGION=us-east-1 TARGET_REGION=ap-northeast-2
export EXPECTED_ACCOUNT_ID="$(jq -r .expected_account_id artifacts/deployment-context.json)"
export BMA_MODEL=openai.gpt-6-luna
export AGENT_BACKEND=bma MODEL_PROCESSING_SCOPE=app_region

aws cloudformation deploy --region "$APP_REGION" \
  --stack-name bma-seoul-build --template-file infra/bootstrap.yaml \
  --parameter-overrides WebFunctionName=bma-seoul-inventory-web

export BMA_CODE_BUCKET="$(aws cloudformation describe-stacks --region "$APP_REGION" \
  --stack-name bma-seoul-build --query 'Stacks[0].Outputs[?OutputKey==`CodeBucket`].OutputValue | [0]' --output text)"
export BMA_ECR_URI="$(aws cloudformation describe-stacks --region "$APP_REGION" \
  --stack-name bma-seoul-build --query 'Stacks[0].Outputs[?OutputKey==`RuntimeRepositoryUri`].OutputValue | [0]' --output text)"

aws ecr get-login-password --region "$APP_REGION" |
  docker login --username AWS --password-stdin "${BMA_ECR_URI%%/*}"
docker tag bma-seoul-runtime:0.1.0 "$BMA_ECR_URI:0.1.0"
docker push "$BMA_ECR_URI:0.1.0"
export BMA_IMAGE_DIGEST="$(aws ecr describe-images --region "$APP_REGION" \
  --repository-name bma-seoul-runtime --image-ids imageTag=0.1.0 --query 'imageDetails[0].imageDigest' --output text)"

aws s3api put-object --region "$APP_REGION" --bucket "$BMA_CODE_BUCKET" \
  --key web/0.1.0.zip --body artifacts/web-function.zip > artifacts/code-upload.json
export BMA_CODE_VERSION="$(jq -r .VersionId artifacts/code-upload.json)"
```

Enter the real access key in the terminal with `read -rs APP_ACCESS_TOKEN`, then export it as an environment
variable. Create the CloudFormation parameter file below locally with mode 0600 and do not commit it to Git.

```bash
read -rs APP_ACCESS_TOKEN
export APP_ACCESS_TOKEN
.venv/bin/python scripts/deployment_parameters.py
aws cloudformation deploy --region "$APP_REGION" \
  --stack-name bma-seoul-inventory --template-file infra/template.yaml \
  --capabilities CAPABILITY_IAM --parameter-overrides file://artifacts/deploy-parameters.json
```

The application stack also creates the CloudFront distribution and OAC, and the Web Function endpoint defaults
to `IamAuth`. Attach the exact distribution-to-endpoint resource policy and verify the edge path with the
[CloudFront OAC runbook](docs/runbooks/cloudfront-oac.md) (`scripts/deploy_cloudfront.py prepare`, `cutover`, then
`scripts/verify_cloudfront.py`). Then open the `WebUrl` output (the CloudFront address) and enter the access key;
`OriginWebUrl` is not a browser entry point. The key stays only in browser memory. Static asset names are not
content-hashed, so invalidate both distributions after each Web release as described in the runbook.
This approach is for demos shared by trusted users; per-user accounts and tenant isolation are not implemented.
When updating, use a new version for the immutable ECR tag and specify the new ZIP's S3 VersionId and image digest.
Do not use `--disable-rollback` for Web Revision replacement updates.
When renaming the stack, also match bootstrap's `WebFunctionName` to the actual function name.
To pass deployment limits, set the `MAX_RESOURCES`, `MAX_PAGES`, `MAX_METRIC_HOURS`, `MAX_DATAPOINTS`, and
`MAX_TURN_SECONDS` environment variables before running `deployment_parameters.py`.
To use a content-hash-based code path, also set `BMA_CODE_KEY`.

## Live Verification

```bash
.venv/bin/python scripts/preflight.py
.venv/bin/python scripts/live_smoke.py
```

The smoke test queries at most 2 returned resources per service, 1 ECS cluster, and the last 15 minutes of
metrics for 1 Lambda function. Even when it reads a service API's minimum page size (for example, EC2 5, RDS 20),
it exports at most 2 resources to the model and results and marks the truncation. The executing principal is
the current local AWS credentials, which is distinct from verifying the deployed Runtime role.

Verification evidence is saved in `artifacts/live-smoke.json` and in Markdown and HTML reports.
The overall verification status and unexecuted items are in [Verification Results](docs/verification.md).

Verify the CloudFront front doors of both apps without new model calls (one small Studio upload is made):

```bash
.venv/bin/python scripts/verify_cloudfront.py
.venv/bin/python scripts/verify_cloudfront_browser.py
```

The checks cover direct-origin 403, preserved Bearer authentication, edge cache hits for public assets, uncached
private responses, existing SSE results and downloads. The 2026-10-27 results and Seoul measurements are in the
[CloudFront deployment record](docs/cloudfront-deployment.md).

## Related Documents

- [BMA operations investigations: follow-up questions, reconnection, procedure catalog](docs/bma-investigations.md)
- [Service API and IAM mapping](docs/api-iam.md)
- [Real AWS deployment and end-to-end verification](docs/aws-deployment.md)
- [Feature extraction and implementation from the original awsops](docs/awsops-extraction.md)
- [Review of additional features to integrate from awsops_v2](docs/awsops-v2-integration-review.md)
- [Korean demo scenario](docs/demo-ko.md)
- [Data processing, networking, cost limits, and unsupported scope](docs/data-and-scope.md)
- [Design](docs/design.md), [implementation plan](docs/implementation-plan.md)
- [Official lifecycle source](runtime/UPSTREAM.md)
- [AI Document Studio usage and verification (Korean)](docs/document-studio.md), [Studio specification](studio/README.md), [ADR-002](docs/decisions/ADR-002-separate-document-studio-stack.md)
- [CloudFront deployment, verification, and Seoul measurements (Korean)](docs/cloudfront-deployment.md), [CloudFront OAC runbook](docs/runbooks/cloudfront-oac.md), [ADR-003](docs/decisions/ADR-003-cloudfront-oac-front-door.md)

Official references: [BMA example repository](https://github.com/openai-on-aws/bedrock-managed-agents),
[AWS BMA guide](https://docs.aws.amazon.com/bedrock/latest/userguide/bedrock-managed-agents-openai.html),
[OpenAI guide for Amazon Bedrock](https://developers.openai.com/api/docs/guides/amazon-bedrock).

---

<a id="korean"></a>

# 한국어

## 개요

AI-Powered AWS Operations Desk는 자연어 질문을 BMA(Bedrock Managed Agents)의 Skills, Python MCP 도구,
실제 AWS 제어 API 조회로 연결합니다. 앱, **BMA, AgentCore Runtime V2, 결과 저장은 `us-east-1`**, 조회 대상은 같은 계정의
**`ap-northeast-2`**입니다. 사용 모델은 Mantle의 **`openai.gpt-6-luna`**입니다.

이 프로젝트의 기존 오레곤 배포를 삭제하고 버지니아 북부로 이전했습니다.
실제 배포 상태와 검증 기록은 [배포 보고서](docs/aws-deployment.md)에서 확인합니다.

원본 `/home/ec2-user/my-project/awsops`에서 추출한 세 범위를 제공합니다.
VPC/EBS/ECR과 관계도, 보고서 이력과 DOCX/PPTX, S3/DynamoDB/ElastiCache/OpenSearch/MSK의
구성 조회와 보안 설정 점검입니다. 현재 **24개 MCP 도구, 4개 Skills, 13개 서비스 범주**를 지원합니다.

저장소에는 별도 데모인 **[AI Document Studio](#ai-document-studio-1)**(`studio/`)도 있습니다. 회사원이 엑셀이나 메모를 넣으면
`openai.gpt-6.1-sol`로 차트, 다이어그램, 편집 가능한 PPTX/DOCX를 만듭니다. 별도 Web Function, 문서 전용 Runtime,
독립 스택에서 실행되며 AWS 리소스 조회 권한이 없습니다.

두 앱은 Lambda Web OAC를 연결한 CloudFront로 제공합니다. 공개 HTML과 정적 파일은
서울 엣지에서 캐싱할 수 있고, API·SSE·개인 문서는 캐싱하지 않습니다.
모델 처리는 계속 us-east-1에서 수행합니다. [운영 절차](docs/runbooks/cloudfront-oac.md),
[CloudFront 배포·검증 기록](docs/cloudfront-deployment.md), 현재 [운영 데스크](docs/aws-deployment.md) /
[문서 스튜디오](docs/document-studio.md) 주소를 참고합니다.

![Operations Desk 기본 화면: 계정과 리전 카드, 지원 서비스, 질문 입력, 완료된 답변](docs/images/ko-overview.png)

## 주요 기능

- **읽기 전용 서울 인벤토리** — STS로 기대 계정을 확인한 뒤에만 등록된 24개 MCP 도구로 `ap-northeast-2` 제어 API를 조회합니다. 임의 명령 실행 도구나 범용 boto3 operation 도구는 없습니다.
- **BMA 스트리밍 답변** — `agent.session.turn.output_text.delta`의 공개 답변을 SSE로 전달하고 react-markdown 10.1.0 + remark-gfm 4.0.1로 렌더링합니다. 조회 단계, 경과 시간, 도구 기록을 표시하며 내부 추론은 표시하지 않습니다.
- **계정 마스킹 보고서** — 저장된 결과를 Markdown/HTML/DOCX/PPTX 보고서로 렌더링하며 계정 ID는 마지막 3자리만 표시합니다. 모델이나 리소스를 다시 조회하지 않습니다.
- **운영 조사** — 같은 BMA 세션에 후속 질문을 보내고, 재접속 후 같은 실행을 복구하며, 버전이 있는 네 가지 운영 절차를 추적합니다.
- **관계도와 보안 점검** — 관계도는 실제 관측된 리소스만 연결하고, 보안 구성 점검은 기준 충족, 확인 필요, 미확인을 구분합니다.
- **CloudFront 접속 경로** — 앱마다 Lambda Web OAC를 연결한 CloudFront 배포로 제공합니다. 리전 오리진은 해당 배포의 요청만 받고(`IamAuth`), 공개 HTML과 정적 파일은 서울 엣지에서 캐시하며, API, SSE, 업로드, 개인 다운로드는 캐시하지 않습니다.
- **AI Document Studio** — XLSX/CSV/TXT/MD 파일 하나나 붙여 넣은 메모로 차트, 다이어그램, 편집 가능한 PPTX/DOCX를 세 가지 스타일로 만듭니다. 실제 진행 단계와 안전한 미리보기를 제공하며, 숫자는 모델이 아니라 코드가 계산합니다.

### 화면

고정된 합성 데이터를 쓰는 샘플 모드(`DATA_MODE=sample`)에서 캡처했습니다. AWS API와 모델을 호출하지 않았고
실제 리소스는 나오지 않습니다. `.venv/bin/python scripts/capture_screenshots.py`로 다시 만들 수 있습니다.

<table>
  <tr>
    <td width="50%" valign="top"><img src="docs/images/ko-answer.png" alt="Markdown 답변과 보고서 다운로드 버튼이 있는 조회 결과 패널"><br><sub><b>스트리밍 답변</b> — 공개 text delta를 Markdown으로 렌더링하고 MD/HTML/DOCX/PPTX로 내려받습니다</sub></td>
    <td width="50%" valign="top"><img src="docs/images/ko-trace.png" alt="소요 시간, 결과 수, 상태, AWS API 호출을 보여 주는 실행 기록 표"><br><sub><b>실행 기록</b> — MCP 호출마다 리전, 소요 시간, 결과 수, 사용한 AWS API를 표시합니다</sub></td>
  </tr>
  <tr>
    <td width="50%" valign="top"><img src="docs/images/ko-topology.png" alt="서브넷, 게이트웨이, 엔드포인트, 보안 그룹이 연결된 VPC 관계도"><br><sub><b>리소스 관계도</b> — 실제 관측된 구성 참조만 연결하고, 선택한 노드의 정규화된 필드를 보여 줍니다</sub></td>
    <td width="50%" valign="top"><img src="docs/images/ko-security.png" alt="기준 충족과 확인 필요 결과가 있는 보안 구성 점검 표"><br><sub><b>보안 구성 점검</b> — 보안 그룹, RDS, EBS 설정을 기준 충족, 확인 필요, 미확인으로 구분합니다</sub></td>
  </tr>
  <tr>
    <td width="50%" valign="top"><img src="docs/images/ko-report-preview.png" alt="서비스별 현황 표가 있는 HTML 보고서 미리보기 창"><br><sub><b>HTML 보고서 미리보기</b> — 저장된 보고서를 sandbox iframe에 표시하며, 열어도 AWS나 모델을 다시 호출하지 않습니다</sub></td>
    <td width="50%" valign="top"><img src="docs/images/ko-history.png" alt="질문, 서비스, 상태가 표시된 보고서 이력 목록"><br><sub><b>보고서 이력</b> — 저장된 실행을 서비스와 상태와 함께 보여 주며, 새 조회 없이 불러옵니다</sub></td>
  </tr>
  <tr>
    <td width="50%" valign="top"><img src="docs/images/ko-investigation.png" alt="절차 단계, 후속 질문 입력, 실행 기록이 있는 운영 조사 화면"><br><sub><b>운영 조사</b> — 버전이 있는 절차, 단계별 상태, 같은 세션에서 이어지는 후속 질문</sub></td>
    <td width="50%" valign="top"><img src="docs/images/ko-mobile.png" alt="너비 390픽셀 모바일 화면"><br><sub><b>모바일 화면</b> — 390px 화면에서 가로 스크롤 없이 표시합니다</sub></td>
  </tr>
  <tr>
    <td colspan="2"><img src="docs/images/ko-dark.png" alt="운영 조사 결과가 표시된 다크 모드 화면"><br><sub><b>다크 모드와 한국어 화면</b> — 상단 막대에서 테마와 언어를 전환합니다</sub></td>
  </tr>
</table>

### AI Document Studio

비개발자를 위한 별도 데모로 [`studio/`](studio/)에 있습니다. XLSX/CSV/TXT/MD 파일 하나(최대 5 MiB)를 올리거나
메모를 붙여 넣고, 원하는 결과를 자연어로 쓴 뒤 PowerPoint, Word, 차트, 다이어그램 출력과 업무 보고서, AWS 운영 데스크,
발표 자료 스타일 중 하나를 고릅니다. BMA(`openai.gpt-6.1-sol`)는 구성과 문장을 쓰고, 제한된 문서 MCP 도구 6개가
실제 값을 집계해 PNG/SVG, 편집 가능한 PPTX/DOCX, HTML 내용 미리보기를 만듭니다. 다운로드에는 인증이 필요하고
파일은 7일 뒤 만료됩니다. 사용법, 한도, 실제 검증은 [document-studio.md](docs/document-studio.md), 배포는
[런북](docs/runbooks/deploy-document-studio.md)을 참고합니다.

화면은 로컬 fixture에서 캡처했습니다. 실제 Studio 화면과 HTTP 경로가 [`studio/examples/`](studio/examples/)의 자료로
실제 Python 렌더러가 만든 파일을 제공하며, 답변 문장만 고정 예시입니다. AWS API와 모델은 호출하지 않았습니다.
`.venv/bin/python scripts/capture_screenshots.py studio`로 다시 만들 수 있습니다.

<table>
  <tr>
    <td colspan="3"><img src="docs/images/ko-studio-result.png" alt="완료된 작업: 답변 요약, 파일 5개, 월별 매출 차트가 들어간 문서 미리보기"><br><sub><b>완성된 문서</b> — 차트 PNG/SVG, PPTX, DOCX, 그리고 올린 엑셀로 집계한 차트가 들어간 HTML 내용 미리보기</sub></td>
  </tr>
  <tr>
    <td width="33%" valign="top"><img src="docs/images/ko-studio-brief.png" alt="엑셀 파일, 요청, 출력 선택, 문서 스타일이 있는 입력 화면"><br><sub><b>요청 입력</b> — 파일 하나나 메모, 자연어 요청, 출력 형식, 세 가지 스타일</sub></td>
    <td width="33%" valign="top"><img src="docs/images/ko-studio-progress.png" alt="완료한 단계, 현재 단계, 경과 시간이 있는 진행 화면"><br><sub><b>진행 상황</b> — 실제 작업 단계와 경과 시간, 임의 백분율 없음</sub></td>
    <td width="33%" valign="top"><img src="docs/images/ko-studio-diagram.png" alt="AWS 운영 데스크 스타일의 업무 흐름도 파일을 보여 주는 이전 작업"><br><sub><b>다이어그램 출력</b> — 메모를 AWS 운영 데스크 스타일의 업무 흐름도로 정리</sub></td>
  </tr>
</table>

## 아키텍처

```mermaid
flowchart LR
  U["Browser"] --> CF["CloudFront / OAC"]
  CF --> W["Lambda Web Function<br/>us-east-1 / IamAuth"]
  W --> B["BMA / Mantle<br/>openai.gpt-6-luna<br/>us-east-1"]
  B --> R["AgentCore Runtime V2<br/>us-east-1"]
  K["4 Skills"] --> R
  R --> M["Python STDIO MCP"]
  M --> S["Seoul AWS control APIs<br/>ap-northeast-2"]
  S --> M
  B -->|"public text delta"| W
  W -->|"SSE / Markdown"| CF
  CF --> U
  W --> O["Normalized app results<br/>S3 / us-east-1"]
```

BMA는 Runtime의 Skills를 읽고 `agent.tools[].transport.type=stdio`로 MCP를 실행합니다.
Runtime 프로토콜은 HTTP, 플랫폼은 V2이며 공식 lifecycle 서버는 변경하지 않았습니다.
Web Function은 STS로 배포 계정을 확인한 뒤 BMA 세션을 만듭니다. MCP는 별도로 Runtime의
실제 계정을 확인하고, 일치할 때만 서울 리소스 API를 호출합니다.

**서울에서 조회한 정보 중 모델에 전달한 내용은 버지니아 북부 BMA에서 분석됩니다.**
서울 조회가 서울 내 처리만을 뜻하지 않습니다. 세부 보존 정책과 네트워크는
[데이터 처리와 범위](docs/data-and-scope.md)에 있습니다. 전체 계층 구조는
[아키텍처 문서](docs/architecture.md)를 참고합니다.

## 사전 요구 사항

- Node.js 24 (`engines.node >= 24`; Web Functions 런타임은 Node.js 24만 지원합니다)
- Python 3.12와 `uv`
- `linux/arm64` 빌드를 지원하는 Docker (Runtime 이미지)
- AWS CLI v2와 `jq` (배포)
- 공식 Codex 0.164.0 Linux ARM64 바이너리 (Runtime 빌드; `scripts/prepare_runtime.py`가 위치를 찾습니다)
- 대상 계정의 AWS 자격증명 (실제 모드, 실제 조회 검증, 배포에만 필요합니다)

## 설치 방법

```bash
# Clone the repository
git clone https://github.com/whchoi98/bma-openai.git
cd bma-openai

# Install Node.js dependencies and build the UI
npm ci --ignore-scripts --prefix web
npm run build --prefix web

# Create the Python environment and install development dependencies
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[dev]'

# Optional: AI Document Studio environment and package link
uv venv --python 3.12 .studio-venv
uv pip install --python .studio-venv/bin/python -r studio/requirements.txt
ln -s ../web/node_modules studio/node_modules
```

## 사용법

Node.js 24에서 샘플 화면을 실행합니다. 샘플은 AWS API와 모델을 호출하지 않습니다.

```bash
DATA_MODE=sample node web/index.js
```

브라우저에서 `http://127.0.0.1:3000`을 엽니다. `DATA_MODE`, 계정과 리전은 서버 설정이며
질문이나 브라우저 입력으로 변경할 수 없습니다. 샘플 계정과 관측 시각은 고정된 fixture입니다.

샘플 모드로 MCP 서버를 실행합니다.

```bash
DATA_MODE=sample .venv/bin/python -m aws_inventory.mcp_server
```

MCP 서버의 stdout은 JSON-RPC 전용입니다. 실제 MCP 클라이언트 연결은 `tests/test_mcp.py`로 검증합니다.

## 환경 설정

| Variable | Description | Default |
|----------|-------------|---------|
| `APP_REGION` | 앱, BMA, Runtime, 결과 저장 리전 | `us-east-1` |
| `TARGET_REGION` | AWS 리소스 조회 대상 리전 | `ap-northeast-2` |
| `EXPECTED_ACCOUNT_ID` | 배포 시 STS로 확인한 계정. CloudFormation은 `AWS::AccountId`로 주입 | (비어 있음) |
| `DATA_MODE` | `live` 또는 `sample`; 누락 설정은 시작 단계에서 거부 | `live` |
| `BMA_MODEL` | us-east-1 Mantle 목록과 BMA 세션 생성으로 확인한 모델 | `openai.gpt-6-luna` |
| `AGENT_BACKEND` | 현재 `bma`; 선택 가능한 대안은 `converse` | `bma` |
| `CONVERSE_MODEL` | Converse 경로의 지정 추론 프로파일 | `global.openai.gpt-6-luna` |
| `MODEL_PROCESSING_SCOPE` | Runtime 데이터 흐름 표시: Converse는 `global`, BMA는 `app_region`; IaC에서 설정 | `app_region` |
| `BMA_RUNTIME_ARN` | 같은 계정의 us-east-1 Runtime ARN | (비어 있음) |
| `BMA_SESSION_ROLE_ARN` | 같은 계정의 지정 BMA 세션 역할 ARN | (비어 있음) |
| `INVESTIGATION_WORKER_ARN` | 같은 계정과 us-east-1의 지정 조사 worker Lambda ARN | (비어 있음) |
| `APP_STATE_BUCKET` | us-east-1 앱 결과 저장 버킷 | (비어 있음) |
| `APP_ACCESS_TOKEN` | 실제 모드 접속 키, 최소 32자. 소스·브라우저 번들에 넣지 않음 | (비어 있음) |
| `MAX_RESOURCES` | 도구당 최대 리소스 수; 값을 줄일 수만 있음 | `100` |
| `MAX_PAGES` | 도구당 최대 페이지 수 | `10` |
| `MAX_METRIC_HOURS` | 한 번에 조회하는 최대 시간, 최근 7일 이내 | `6` |
| `MAX_DATAPOINTS` | 최대 데이터 포인트 수, 300초 버킷 | `1440` |
| `MAX_TURN_SECONDS` | 에이전트 실행·스트림 한도; 현재 배포는 300초 | `180` |

`AWS_REGION` 전체를 서울로 바꾸지 않습니다. 조회 boto3 클라이언트는
`region_name=TARGET_REGION`, STS·BMA 서명·앱 S3는 `APP_REGION`을 명시합니다.
Runtime의 공식 lifecycle이 사용하는 `AWS_REGION`은 버지니아 북부입니다.

Web Function은 BMA 호출·지정 세션 역할 AssumeRole·앱 결과 저장 권한을 가지며 서울 조회 권한이 없습니다.
세션 역할은 선택 모델과 지정 Runtime만 사용합니다. 조회 권한은 Runtime 역할에만 있습니다.
운영 조사 worker는 BMA 세션 API와 제한된 앱 상태만 사용하며 직접 AWS 리소스를 조회하지 않습니다.
관리형 `ReadOnlyAccess`, 임의 명령 실행 MCP, 범용 boto3 operation 도구는 추가하지 않았습니다.

## 프로젝트 구조

```text
bma-openai/
├── .claude/              # Claude Code 설정, hook, skill, 명령, 에이전트
├── aws_inventory/        # 계정 검증, 고정 리전 boto3 클라이언트, 24개 MCP 도구, 정규화와 한도
├── docs/                 # 설계, 배포, 데이터 범위, 운영 조사 문서
│   ├── architecture.md   # 시스템 아키텍처 문서
│   ├── images/           # scripts/capture_screenshots.py로 만든 README 스크린샷
│   ├── reference/        # 계층별 구현 참조 문서
│   ├── runbooks/         # 운영 런북
│   └── decisions/        # 아키텍처 결정 기록(ADR)
├── infra/                # CloudFormation bootstrap 스택과 애플리케이션 스택
├── runtime/              # 공식 BMA lifecycle 서버, HTTP→STDIO MCP bridge, ARM64 Dockerfile
├── scripts/              # 사전 확인, 빌드, 배포, 실제 조회 검증 스크립트
├── skills/               # Runtime 이미지에 포함되는 BMA Skills 4개
├── studio/               # AI Document Studio: 문서 MCP/렌더러, Web Function, Skills, 스택, 테스트
├── tests/                # Python 테스트와 tests/run-all.sh 하네스 테스트
├── web/                  # Node.js 24 Web Function, BMA/Converse 클라이언트, 보고서, React 답변 컴포넌트
└── webapp/               # Python 로컬 참조 앱과 공통 정적 화면
```

### 주요 파일

| 경로 | 역할 |
| --- | --- |
| `aws_inventory/` | 계정/소유자 검증, 고정 리전 boto3 클라이언트, 24개 MCP 도구, 정규화·한도 |
| `skills/` | 인벤토리·상태 확인·운영 보고서 Skills |
| `runtime/` | 공식 BMA lifecycle 서버, 제한된 HTTP→STDIO MCP bridge, ARM64 Dockerfile |
| `web/` | Node.js 24 BMA/Converse 클라이언트·웹 서버·보고서, React 답변 컴포넌트 |
| `webapp/static/` | 두 리전·실제/샘플 모드·조회 기록을 표시하는 공통 화면 |
| `webapp/` | Python 로컬 참조 HTTP 앱, 고정 응답 생성 및 로컬 보고서 작성 |
| `infra/` | 역할 4개, Runtime V2, Web Function, 조사 worker Lambda, 앱 S3 |
| `scripts/` | 계정 사전 확인, 빌드, 소규모 실제 조회 |
| `tests/`, `web/tests/` | Stubber, MCP STDIO, HTTP/SSE, IAM 정책 범위 검증 |
| `studio/` | AI Document Studio: 입력 해석, 차트 집계, Office 렌더러, 작업 고정 MCP, 별도 Web Function·worker·스택 |

## 테스트

```bash
# Python tests (Stubber, MCP STDIO, IAM policy scope, CloudFront templates and deployer)
.venv/bin/python -m pytest

# Node.js tests (BMA/Converse clients, HTTP/SSE, cache headers, reports, investigations)
npm test --prefix web

# Lint
.venv/bin/ruff check .

# Claude Code harness tests (hooks, secret patterns, project structure)
bash tests/run-all.sh

# AI Document Studio (parsing, rendering, MCP, IAM scope, HTTP/worker)
.studio-venv/bin/python -m unittest studio.tests.test_input_data studio.tests.test_render studio.tests.test_job
.venv/bin/python -m unittest studio.tests.test_infra
node --test studio/tests/backend.test.js studio/tests/cache-control.test.js
```

## API 문서

Web Function은 `/health`와 `/api/*` 경로를 제공합니다. `/api/context`, `/api/chat`(SSE), `/api/runs`,
`/api/runs/{id}`, `/api/runs/{id}/report.{md|html|docx|pptx}`, `/api/procedures`, 그리고 turn·event·cancel
하위 경로를 가진 `/api/investigations`입니다. 접속 키가 설정되어 있으면 `/api/*`는
`Authorization: Bearer <APP_ACCESS_TOKEN>`이 필요하며, 인증하지 않은 API 요청은 401을 반환합니다.
요청과 응답의 세부 내용은 [API 레퍼런스](docs/api-reference.md)를 참고합니다. 별도
[AI Document Studio API](docs/api-reference.md#ai-document-studio-api-1)(`/api/config`, `/api/uploads`, `/api/jobs/**`)도 같은 문서에 있습니다.

## 기여 방법

1. 저장소를 Fork합니다
2. 브랜치를 만듭니다 (`git checkout -b feat/amazing-feature`)
3. 변경 사항을 커밋합니다 (`git commit -m 'feat: add amazing feature'`)
4. 브랜치에 Push합니다 (`git push origin feat/amazing-feature`)
5. Pull Request를 엽니다

커밋 메시지는 [Conventional Commits](https://www.conventionalcommits.org/)를 따릅니다.

```bash
git commit -m "feat: add ElastiCache encryption check"
git commit -m "fix: mask account IDs split across Markdown emphasis"
git commit -m "docs: update deployment runbook"
```

## 라이선스

이 프로젝트는 [MIT No Attribution (MIT-0)](LICENSE) 라이선스를 따릅니다.
`runtime/lifecycle/server.py`는 공식 `@aws/agentcore` npm 패키지 1.0.0의 파일을 변경 없이 포함했으며,
원본 Apache License 2.0인 [runtime/LICENSE-AGENTCORE](runtime/LICENSE-AGENTCORE)를 따릅니다.
출처는 [runtime/UPSTREAM.md](runtime/UPSTREAM.md)에 있습니다.

## 연락처

- 메인테이너: [WooHyung Choi (whchoi98)](https://github.com/whchoi98)
- 이슈: [github.com/whchoi98/bma-openai/issues](https://github.com/whchoi98/bma-openai/issues)

## 모델, 화면과 스트리밍

- 현재 구성은 `AGENT_BACKEND=bma`, `BMA_MODEL=openai.gpt-6-luna`입니다.
  `agent.session.turn.output_text.delta`의 공개 답변을 SSE로 즉시 전달합니다.
- 기존 `AGENT_BACKEND=converse` 구현은 선택 가능한 대안으로 남아 있습니다.
  이 경로는 `global.openai.gpt-6-luna`와 `ConverseStreamCommand`를 사용하며
  글로벌 처리 범위를 별도로 표시합니다. 현재 BMA 배포에는 글로벌 추론 권한을 부여하지 않습니다.
- 답변은 **react-markdown 10.1.0 + remark-gfm 4.0.1**로 렌더링합니다.
  조회 단계, 경과 시간과 도구 기록을 표시하며 내부 추론은 표시하거나 저장하지 않습니다.
- 폰트는 로컬 NAVER **나눔스퀘어 OTF Bold**입니다. OFL 라이선스를 포함하고 CDN을 사용하지 않습니다.
- 상단에서 다크 모드와 한국어/English를 전환하며 실제 모델 ID와 실행/조회 리전을 표시합니다.
- 화면과 Markdown/HTML/DOCX/PPTX 보고서의 계정 ID는 마지막 3자리만 표시합니다.
  STS 비교와 S3의 원본 근거는 전체 계정 ID를 유지합니다.
- **HTML 보고서 보기**는 저장된 보고서를 렌더링합니다. 이력 로드, 미리보기와 문서 변환은
  모델이나 리소스를 다시 조회하지 않습니다.
- 관계도는 실제 관측된 리소스만 연결합니다. 보안 구성 점검은 기준 충족, 확인 필요, 미확인을 구분합니다.
- **운영 조사**에서는 같은 BMA 세션에 후속 질문을 보내고, 재접속 후 같은 실행을 복구합니다.
  네 가지 운영 절차의 버전과 실제 단계 상태를 표시하며 이전 근거의 원본 시각을 보존합니다.
  기존 **단일 질문** 모드는 질문마다 새 세션을 만듭니다. [사용 방법](docs/bma-investigations.md)을 참고합니다.

## 배포 준비

먼저 배포 주체의 계정과 모델 목록을 확인합니다. 모델 목록 조회는 추론 호출이 아닙니다.

```bash
.venv/bin/python scripts/preflight.py --list-models
.venv/bin/python scripts/prepare_runtime.py
docker build --platform linux/arm64 -f runtime/Dockerfile -t bma-seoul-runtime:0.1.0 .
.venv/bin/python scripts/build_web.py
```

`prepare_runtime.py`는 공식 설치된 **Codex 0.164.0 Linux ARM64** 바이너리를 찾습니다.
다른 위치라면 `--source /path/to/codex`를 지정합니다. 버전·ELF 아키텍처·exec-server 옵션을 검사합니다.
Web Function ZIP에는 Node.js 코드와 의존성·정적 화면이 들어갑니다.
`artifacts/deployment-context.json`은 확인한 실제 계정을 기록하며, 다음 검증에서 계정이 바뀌면
기존 기대 계정을 덮어쓰지 않고 중단합니다.

아래는 배포를 재현하는 명령입니다. 현재 배포와 실제 검증 결과는
[AWS 배포 보고서](docs/aws-deployment.md)에 기록했습니다. 단계별 운영 절차는
[배포 런북](docs/runbooks/deploy-production.md)을 따릅니다.

```bash
export APP_REGION=us-east-1 TARGET_REGION=ap-northeast-2
export EXPECTED_ACCOUNT_ID="$(jq -r .expected_account_id artifacts/deployment-context.json)"
export BMA_MODEL=openai.gpt-6-luna
export AGENT_BACKEND=bma MODEL_PROCESSING_SCOPE=app_region

aws cloudformation deploy --region "$APP_REGION" \
  --stack-name bma-seoul-build --template-file infra/bootstrap.yaml \
  --parameter-overrides WebFunctionName=bma-seoul-inventory-web

export BMA_CODE_BUCKET="$(aws cloudformation describe-stacks --region "$APP_REGION" \
  --stack-name bma-seoul-build --query 'Stacks[0].Outputs[?OutputKey==`CodeBucket`].OutputValue | [0]' --output text)"
export BMA_ECR_URI="$(aws cloudformation describe-stacks --region "$APP_REGION" \
  --stack-name bma-seoul-build --query 'Stacks[0].Outputs[?OutputKey==`RuntimeRepositoryUri`].OutputValue | [0]' --output text)"

aws ecr get-login-password --region "$APP_REGION" |
  docker login --username AWS --password-stdin "${BMA_ECR_URI%%/*}"
docker tag bma-seoul-runtime:0.1.0 "$BMA_ECR_URI:0.1.0"
docker push "$BMA_ECR_URI:0.1.0"
export BMA_IMAGE_DIGEST="$(aws ecr describe-images --region "$APP_REGION" \
  --repository-name bma-seoul-runtime --image-ids imageTag=0.1.0 --query 'imageDetails[0].imageDigest' --output text)"

aws s3api put-object --region "$APP_REGION" --bucket "$BMA_CODE_BUCKET" \
  --key web/0.1.0.zip --body artifacts/web-function.zip > artifacts/code-upload.json
export BMA_CODE_VERSION="$(jq -r .VersionId artifacts/code-upload.json)"
```

실제 접속 키는 터미널에서 `read -rs APP_ACCESS_TOKEN`으로 입력한 뒤 환경 변수로 내보냅니다.
아래 CloudFormation parameter 파일은 로컬에서 모드 0600으로 만들고 Git에 포함하지 않습니다.

```bash
read -rs APP_ACCESS_TOKEN
export APP_ACCESS_TOKEN
.venv/bin/python scripts/deployment_parameters.py
aws cloudformation deploy --region "$APP_REGION" \
  --stack-name bma-seoul-inventory --template-file infra/template.yaml \
  --capabilities CAPABILITY_IAM --parameter-overrides file://artifacts/deploy-parameters.json
```

애플리케이션 스택은 CloudFront 배포와 OAC도 만들며, Web Function 엔드포인트의 기본 인증 방식은 `IamAuth`입니다.
[CloudFront OAC 운영 절차](docs/runbooks/cloudfront-oac.md)에 따라 정확한 배포-엔드포인트 리소스 정책을 연결하고
엣지 경로를 검증합니다(`scripts/deploy_cloudfront.py prepare`, `cutover`, 이어서 `scripts/verify_cloudfront.py`).
그다음 `WebUrl` 출력(CloudFront 주소)으로 접속해 접속 키를 입력합니다. `OriginWebUrl`은 브라우저 접속 주소가 아닙니다.
키는 브라우저 메모리에만 유지합니다. 정적 자산 이름에 내용 해시가 없으므로 Web 배포 뒤에는 운영 절차에 따라 두 배포의
캐시를 무효화합니다.
이 방식은 신뢰된 사용자가 함께 쓰는 데모용이며 사용자별 계정·테넌트 격리는 구현하지 않았습니다.
업데이트할 때는 ECR의 불변 태그에 새 버전을 사용하고 새 ZIP의 S3 VersionId와 이미지 digest를 지정합니다.
Web Revision 교체 업데이트에는 `--disable-rollback`을 사용하지 않습니다.
스택 이름을 바꿀 때는 bootstrap의 `WebFunctionName`도 실제 함수 이름과 일치시킵니다.
배포 한도는 `MAX_RESOURCES`, `MAX_PAGES`, `MAX_METRIC_HOURS`, `MAX_DATAPOINTS`,
`MAX_TURN_SECONDS` 환경 변수를 설정한 뒤 `deployment_parameters.py`로 전달할 수 있습니다.
내용 해시 기반 코드 경로를 사용하려면 `BMA_CODE_KEY`도 설정합니다.

## 실제 조회 검증

```bash
.venv/bin/python scripts/preflight.py
.venv/bin/python scripts/live_smoke.py
```

서비스별 반환 리소스 최대 2개, ECS 클러스터 1개, Lambda 함수 1개의 최근 15분 지표만 조회합니다.
서비스 API의 최소 페이지 크기(예: EC2 5, RDS 20)만큼 읽은 경우에도 모델·결과에는 최대 2개만 내보내고
잘림을 표시합니다. 실행 주체는 현재 로컬 AWS 자격증명이며 배포된 Runtime 역할 검증과 구분합니다.

검증 근거는 `artifacts/live-smoke.json`, Markdown·HTML 보고서에 저장합니다.
전체 검증 상태와 미실행 항목은 [검증 결과](docs/verification.md)에 있습니다.

두 앱의 CloudFront 접속 경로는 새 모델 호출 없이 검증합니다(Studio에 작은 파일 하나를 업로드합니다).

```bash
.venv/bin/python scripts/verify_cloudfront.py
.venv/bin/python scripts/verify_cloudfront_browser.py
```

오리진 직접 접근 403, Bearer 인증 유지, 공개 자산의 엣지 캐시 적중, 비공개 응답의 캐시 제외, 기존 SSE 결과와 다운로드를
확인합니다. 2026-10-27 결과와 서울 측정값은 [CloudFront 배포 기록](docs/cloudfront-deployment.md)에 있습니다.

## 관련 문서

- [BMA 운영 조사: 후속 질문, 재접속, 절차 카탈로그](docs/bma-investigations.md)
- [서비스별 API·IAM 대응표](docs/api-iam.md)
- [실제 AWS 배포 및 종단 간 검증](docs/aws-deployment.md)
- [원본 awsops 기능 추출과 구현](docs/awsops-extraction.md)
- [awsops_v2에서 추가로 연동할 수 있는 기능 검토](docs/awsops-v2-integration-review.md)
- [한국어 데모 시나리오](docs/demo-ko.md)
- [데이터 처리·네트워크·비용 한도·미지원 범위](docs/data-and-scope.md)
- [설계](docs/design.md), [구현 계획](docs/implementation-plan.md)
- [공식 lifecycle 출처](runtime/UPSTREAM.md)
- [AI Document Studio 사용 안내와 검증](docs/document-studio.md), [Studio 명세](studio/README.md), [ADR-002](docs/decisions/ADR-002-separate-document-studio-stack.md)
- [CloudFront 배포, 검증, 서울 측정](docs/cloudfront-deployment.md), [CloudFront OAC 운영 절차](docs/runbooks/cloudfront-oac.md), [ADR-003](docs/decisions/ADR-003-cloudfront-oac-front-door.md)

공식 참조: [BMA 예제 저장소](https://github.com/openai-on-aws/bedrock-managed-agents),
[AWS BMA 가이드](https://docs.aws.amazon.com/bedrock/latest/userguide/bedrock-managed-agents-openai.html),
[OpenAI의 Amazon Bedrock 가이드](https://developers.openai.com/api/docs/guides/amazon-bedrock).
