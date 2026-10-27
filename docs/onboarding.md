# Developer Onboarding

<a href="#english"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English"></a>
<a href="#korean"><img src="https://img.shields.io/badge/lang-한국어-red.svg" alt="Korean"></a>

---

<a id="english"></a>

# English

## Quick Start

### 1. Prerequisites
- [ ] Python 3.12 and [`uv`](https://docs.astral.sh/uv/) installed
- [ ] Node.js 24 installed (`node --version` shows `v24.x`)
- [ ] Repository access granted
- [ ] Environment variables reviewed (see `.env.example`); sample mode needs none of the AWS values
- [ ] For Runtime builds only: Docker with `linux/arm64` support and the official Codex 0.164.0 Linux ARM64 binary
- [ ] For deployment only: AWS CLI v2, `jq`, credentials for the pinned deployment account

### 2. Setup
```bash
git clone https://github.com/whchoi98/bma-openai.git
cd bma-openai
bash scripts/setup.sh          # .venv, Python deps, web/node_modules, .env, git hooks
```

### 3. Verify
```bash
.venv/bin/python -m pytest
npm test --prefix web
.venv/bin/ruff check .
bash tests/run-all.sh

# Run the UI with fixed sample data (no AWS API or model calls)
npm run build --prefix web
DATA_MODE=sample node web/index.js   # open http://127.0.0.1:3000

# AI Document Studio (separate venv and node_modules link; no AWS API or model calls)
uv venv --python 3.12 .studio-venv && uv pip install --python .studio-venv/bin/python -r studio/requirements.txt
ln -s ../web/node_modules studio/node_modules
.studio-venv/bin/python -m unittest studio.tests.test_input_data studio.tests.test_render studio.tests.test_job
.venv/bin/python -m unittest studio.tests.test_infra
node --test studio/tests/backend.test.js studio/tests/cache-control.test.js
```

## Project Overview
- Read `CLAUDE.md` for project context and conventions, then the module `CLAUDE.md` of the directory you change
- Read `docs/architecture.md` for system design and `docs/reference/INDEX.md` for layer details
- Review `docs/decisions/` for architectural decisions
- Current deployment and evidence: `docs/aws-deployment.md`, `docs/verification.md`

## Development Workflow
- Branch naming: `feat/`, `fix/`, `docs/`, `refactor/`
- Commit convention: Conventional Commits (`feat: add msk broker health tool`, `fix: mask account id in pptx footer`)
- PR process: run the four commands in Verify, describe live AWS checks separately from local tests, and link evidence in `artifacts/` when a deployment changed
- The `commit-msg` hook removes `Co-Authored-By` lines; the `pre-commit` hook runs `.claude/hooks/secret-scan.sh --staged`

## Key Concepts
- **`APP_REGION` vs `TARGET_REGION`** — `us-east-1` runs the app, BMA, Runtime and storage; `ap-northeast-2` is only queried. Clients always receive the region explicitly.
- **`DATA_MODE`** — `sample` uses deterministic fixtures with no AWS or model calls; `live` requires every setting and rejects missing ones at startup.
- **`AGENT_BACKEND`** — `bma` (current) keeps model processing in `us-east-1`; `converse` uses the global profile `global.openai.gpt-6-luna`.
- **Result envelope** — every tool returns `status` (`ok`, `empty`, `access_denied`, `unsupported_service`, `api_error`, `partial`, `account_mismatch`, `invalid_input`) with `truncated`, `pagination_complete` and `errors`.
- **Generated files** — `web/contract.json`, `web/sample-data.json` (from `scripts/export_web_contract.py`) and `webapp/static/app.js` (from `npm run build --prefix web`).
- **Privacy** — account IDs show only the last 3 digits in UI and reports; reasoning and raw command output are never stored.

## Troubleshooting
| Symptom | Cause | Fix |
|---|---|---|
| Node tests fail on tool names or Skills hashes | `web/contract.json` is stale | `.venv/bin/python scripts/export_web_contract.py` |
| UI change does not appear | `webapp/static/app.js` not rebuilt | `npm run build --prefix web` |
| MCP client reports a JSON-RPC parse error | Something printed to stdout in `aws_inventory/` | Log to stderr instead |
| Live mode exits at startup | Missing `EXPECTED_ACCOUNT_ID`, ARNs or bucket | Use `DATA_MODE=sample` locally, or set all values |
| Commit blocked by `[secret-scan]` | A secret-like string in a staged file | Move it to `.env` or `artifacts/`; build test strings at runtime |

## Resources
- [README](../README.md), [architecture](architecture.md), [API reference](api-reference.md)
- [Deployment runbook](runbooks/deploy-production.md), [API and IAM mapping](api-iam.md)
- [BMA operations investigations](bma-investigations.md), [Data and scope](data-and-scope.md)
- [AI Document Studio](document-studio.md) (Korean), [Studio module](../studio/CLAUDE.md), [Studio deployment runbook](runbooks/deploy-document-studio.md)
- [CloudFront OAC runbook](runbooks/cloudfront-oac.md), [CloudFront deployment record](cloudfront-deployment.md) (Korean), [ADR-003](decisions/ADR-003-cloudfront-oac-front-door.md)

---

<a id="korean"></a>

# 한국어

## 빠른 시작

### 1. 사전 요구 사항
- [ ] Python 3.12와 [`uv`](https://docs.astral.sh/uv/)를 설치합니다
- [ ] Node.js 24를 설치합니다(`node --version`이 `v24.x`)
- [ ] 저장소 접근 권한을 받습니다
- [ ] 환경 변수를 확인합니다(`.env.example` 참고). 샘플 모드에는 AWS 값이 필요하지 않습니다
- [ ] Runtime 빌드 시에만: `linux/arm64`를 지원하는 Docker와 공식 Codex 0.164.0 Linux ARM64 바이너리
- [ ] 배포 시에만: AWS CLI v2, `jq`, 고정된 배포 계정의 자격증명

### 2. 설정
```bash
git clone https://github.com/whchoi98/bma-openai.git
cd bma-openai
bash scripts/setup.sh          # .venv, Python deps, web/node_modules, .env, git hooks
```

### 3. 확인
```bash
.venv/bin/python -m pytest
npm test --prefix web
.venv/bin/ruff check .
bash tests/run-all.sh

# Run the UI with fixed sample data (no AWS API or model calls)
npm run build --prefix web
DATA_MODE=sample node web/index.js   # open http://127.0.0.1:3000

# AI Document Studio (separate venv and node_modules link; no AWS API or model calls)
uv venv --python 3.12 .studio-venv && uv pip install --python .studio-venv/bin/python -r studio/requirements.txt
ln -s ../web/node_modules studio/node_modules
.studio-venv/bin/python -m unittest studio.tests.test_input_data studio.tests.test_render studio.tests.test_job
.venv/bin/python -m unittest studio.tests.test_infra
node --test studio/tests/backend.test.js studio/tests/cache-control.test.js
```

## 프로젝트 개요
- `CLAUDE.md`에서 프로젝트 맥락과 규칙을 읽고, 변경할 디렉터리의 모듈 `CLAUDE.md`를 읽습니다
- 시스템 설계는 `docs/architecture.md`, 계층별 상세는 `docs/reference/INDEX.md`에서 확인합니다
- 아키텍처 결정은 `docs/decisions/`에서 확인합니다
- 현재 배포와 근거는 `docs/aws-deployment.md`, `docs/verification.md`에 있습니다

## 개발 워크플로
- 브랜치 이름: `feat/`, `fix/`, `docs/`, `refactor/`
- 커밋 규칙: Conventional Commits(`feat: add msk broker health tool`, `fix: mask account id in pptx footer`)
- PR 절차: 확인 단계의 네 명령을 실행하고, 실제 AWS 검증은 로컬 테스트와 구분해 적으며, 배포가 바뀌었다면 `artifacts/`의 근거를 연결합니다
- `commit-msg` hook은 `Co-Authored-By` 줄을 제거하고, `pre-commit` hook은 `.claude/hooks/secret-scan.sh --staged`를 실행합니다

## 핵심 개념
- **`APP_REGION`과 `TARGET_REGION`** — `us-east-1`은 앱, BMA, Runtime, 저장소를 실행하고 `ap-northeast-2`는 조회만 합니다. 클라이언트에는 항상 리전을 명시합니다.
- **`DATA_MODE`** — `sample`은 AWS나 모델을 호출하지 않는 고정 fixture를 쓰고, `live`는 모든 설정을 요구하며 누락 시 시작 단계에서 거부합니다.
- **`AGENT_BACKEND`** — `bma`(현재)는 모델 처리를 `us-east-1`에 유지하고, `converse`는 글로벌 프로파일 `global.openai.gpt-6-luna`를 사용합니다.
- **결과 형식** — 모든 도구는 `status`(`ok`, `empty`, `access_denied`, `unsupported_service`, `api_error`, `partial`, `account_mismatch`, `invalid_input`)와 `truncated`, `pagination_complete`, `errors`를 반환합니다.
- **생성 파일** — `web/contract.json`, `web/sample-data.json`(`scripts/export_web_contract.py`로 생성), `webapp/static/app.js`(`npm run build --prefix web`로 생성)입니다.
- **개인정보** — 화면과 보고서의 계정 ID는 마지막 3자리만 표시하며, reasoning과 명령 원문은 저장하지 않습니다.

## 문제 해결
| Symptom | Cause | Fix |
|---|---|---|
| Node tests fail on tool names or Skills hashes | `web/contract.json` is stale | `.venv/bin/python scripts/export_web_contract.py` |
| UI change does not appear | `webapp/static/app.js` not rebuilt | `npm run build --prefix web` |
| MCP client reports a JSON-RPC parse error | Something printed to stdout in `aws_inventory/` | Log to stderr instead |
| Live mode exits at startup | Missing `EXPECTED_ACCOUNT_ID`, ARNs or bucket | Use `DATA_MODE=sample` locally, or set all values |
| Commit blocked by `[secret-scan]` | A secret-like string in a staged file | Move it to `.env` or `artifacts/`; build test strings at runtime |

## 참고 자료
- [README](../README.md), [아키텍처](architecture.md), [API 참조](api-reference.md)
- [배포 런북](runbooks/deploy-production.md), [API·IAM 대응표](api-iam.md)
- [BMA 운영 조사](bma-investigations.md), [데이터 처리와 범위](data-and-scope.md)
- [AI Document Studio 사용 안내](document-studio.md), [Studio 모듈](../studio/CLAUDE.md), [Studio 배포 런북](runbooks/deploy-document-studio.md)
- [CloudFront OAC 운영 절차](runbooks/cloudfront-oac.md), [CloudFront 배포 기록](cloudfront-deployment.md), [ADR-003](decisions/ADR-003-cloudfront-oac-front-door.md)
