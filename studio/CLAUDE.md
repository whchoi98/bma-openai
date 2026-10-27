# studio Module

## Role
AI Document Studio: a separate demo that turns one XLSX/CSV/TXT/MD file or pasted notes into charts,
diagrams and editable PPTX/DOCX through BMA (deployed model `openai.gpt-6.1-sol`). It has its own Lambda
Web Function, worker, document-only AgentCore Runtime, private S3 bucket and stacks (`bma-office-build`,
`bma-office-studio`) in us-east-1, and no AWS resource-query permissions. Spec: `README.md`; usage and
limits: `../docs/document-studio.md`.

## Key Files
- `document_tools/` — Runtime Python (MCP over STDIO, `--job-id UUID` fixes the job)
  - `mcp_server.py` — 6 tools: `inspect_inputs`, `read_table`, `read_text`, `create_chart`, `create_diagram`, `create_documents`
  - `job.py` — `DocumentJob`: input manifest, tool arguments (pydantic), artifact staging and limits
  - `input_data.py` — bounded XLSX/CSV/text parsing, `aggregate_chart()` (saved formula values only, no recalculation)
  - `render.py`, `styles.py` — chart/diagram PNG+SVG, PPTX/DOCX, sandboxed HTML preview; styles `business`, `aws-desk`, `presentation`
- `web/` — Node.js 24 Web Function: `server.js` (routes, Bearer auth, CSP), `jobs.js`, `store.js` (S3 conditional writes), `worker.js` (BMA session per job), `config.js` (`LIMITS`, `STYLES`, `publicJob`)
- `web/static/` — UI (`index.html`, `app.js`, `style.css`, NanumSquare OTF + `OFL.txt`); zipped as-is
- `skills/` — 3 Skills: `document-data-chart`, `document-diagram`, `document-office-composer`
- `infra/bootstrap.yaml` (ECR `bma-office-runtime` + code bucket), `infra/template.yaml` (roles, Runtime, Web Function, worker, data bucket)
- The main template also owns Studio's CloudFront distribution and Lambda Web OAC. `WebUrl` is the public CDN address; `OriginWebUrl` uses `IamAuth`. Apply the exact distribution-to-endpoint resource policy with `scripts/deploy_cloudfront.py`; see `docs/runbooks/cloudfront-oac.md`.
- `RuntimeDockerfile` — reuses `runtime/bin/codex`, `runtime/lifecycle/server.py`; installs `requirements.txt`
- `scripts/` — `build_web.py`, `deploy.py` (live), `verify_live.py` / `verify_browser.py` (live), `render_fixtures.py` + `fixture_server.mjs` (local README screenshots)
- `examples/` — demo inputs (Korean and English); `tests/` — unittest + node:test suites

## Rules
- Keep Studio isolated: never add Operations Desk tools, AWS inventory permissions or generic shell/Python execution tools here, and never widen the desk stacks for Studio.
- The model writes structure and wording only; numbers come from `aggregate_chart()`. Never fill missing values or invent data.
- `scripts/build_web.py` zips all of `studio/web/` plus `web/bma.js`, `web/contract.json` and production `web/node_modules`. Put no docs under `studio/web/`; changes to `web/bma.js` affect Studio too. Locally, run `ln -s ../web/node_modules studio/node_modules` (gitignored) so Studio modules resolve packages.
- Templates, `config.js` and `deploy.py` default to `openai.gpt-6-luna`; the live stack runs Sol because `artifacts/studio/deployment.json` sets `model`. Check it before `main`/`update`.
- Only the last job ID and display preferences may persist in the browser; keys, files and notes must not.
- Never cache `/api/*`, SSE, uploads or document downloads. Inline CloudFront forwarding keeps their TTL at zero and retains Authorization, Content-Type and X-File-Name without forwarding viewer Host. Public HTML caches for 60 seconds and static assets for up to one hour at the edge.
- Tests (no AWS or model calls):
  - `.studio-venv/bin/python -m unittest studio.tests.test_input_data studio.tests.test_render studio.tests.test_job`
  - `.venv/bin/python -m unittest studio.tests.test_infra` (needs PyYAML)
  - `node --test studio/tests/backend.test.js studio/tests/cache-control.test.js studio/tests/frontend.test.mjs` (browser test runs when `STUDIO_PLAYWRIGHT` points at Playwright's `index.mjs`; `STUDIO_CHROMIUM` overrides the browser)
- Create the venv with `uv venv --python 3.12 .studio-venv && uv pip install --python .studio-venv/bin/python -r studio/requirements.txt`.
- Ask before `deploy.py`, `verify_live.py` or `verify_browser.py`: real account, model and cost. Follow `docs/runbooks/deploy-document-studio.md`.
