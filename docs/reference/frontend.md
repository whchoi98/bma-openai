# Frontend / Frontend 구현 상세

<a href="#english"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English"></a>
<a href="#korean"><img src="https://img.shields.io/badge/lang-한국어-red.svg" alt="Korean"></a>

<a id="english"></a>
## English

### 1. Overview
The frontend layer is the Node.js 24 Web Function in `web/`: a dependency-light `node:http` server that authenticates `/api/*`, verifies the deployment account with STS, drives BMA (or the optional Converse backend), streams Server-Sent Events, stores results in S3 and renders Markdown, HTML, DOCX and PPTX reports. Its browser bundle is a React 19 app under `web/ui/` compiled by esbuild into `webapp/static/app.js`. It exists because Lambda Web Functions run only Node.js 24; the Python `webapp/` is a local reference implementation.

### 2. Components
| Component | Path | Purpose |
|---|---|---|
| HTTP server | `web/server.js` | Static files, `/health`, `/api/context`, `/api/chat` SSE, `/api/runs*` history and reports; bearer auth and security headers |
| Entry and settings | `web/index.js`, `web/settings.js` | Listens on `AWS_LAMBDA_HTTP_ENDPOINT` (default `127.0.0.1:3000`); validates environment configuration at startup |
| Agent runners | `web/runners.js`, `web/bma.js`, `web/converse.js` | `SampleRunner` fixtures, `LiveRunner` over the SigV4-signed BMA client, optional `ConverseRunner` with `RuntimeMcp` |
| Result stores | `web/stores.js`, `web/history.js` | `MemoryStore` (sample) and `S3Store` (live) with history index, record size limits and validation |
| Reports | `web/reports.js`, `web/office-reports.js`, `web/report-rendering.js` | Markdown and HTML renderers; DOCX (`docx` 9.6.1) and PPTX (`pptxgenjs` 4.0.1) with input, output and slide limits |
| Investigations | `web/investigations.js`, `web/investigation-routes.js`, `web/investigation-store.js`, `web/investigation-worker.js`, `web/investigation-executor.js`, `web/procedures.js` | Multi-turn BMA investigations, S3 snapshots with conditional writes, async worker dispatch, versioned procedure catalog |
| Browser UI source | `web/ui/app.js`, `web/ui/investigations.js`, `web/ui/history-panel.js`, `web/ui/resource-insights.js`, `web/markdown.js` | React 19 screens; streaming answer rendered by react-markdown 10.1.0 + remark-gfm 4.0.1 |
| UI build | `web/build-ui.mjs` | esbuild bundle (IIFE, ES2022, minified) to `webapp/static/app.js` |
| Tests | `web/tests/*.test.js` | `node --test` suites for server, BMA, Converse, history, investigations, reports and UI |

### 3. Key Decisions
- Use `node:http` instead of a web framework — the Web Function ZIP stays small and every route, header and status code is explicit in `web/server.js`.
- Allow at most two concurrent `/api/chat` streams per environment and send a heartbeat every 15 s — protects the 180 s turn budget and keeps idle proxies from closing the SSE connection.
- Keep the Converse backend selectable but off (`AGENT_BACKEND=bma`) — its `global.openai.gpt-6-luna` profile changes the data processing scope, so it is shown separately and not granted in the BMA deployment (`docs/data-and-scope.md`).
- Run investigations through a separate worker Lambda with S3 snapshots — the browser can reconnect and resume the same run without holding a long request open (`docs/bma-investigations.md`).
- Render report previews and downloads from stored records only — opening a report never repeats model inference or AWS reads.

### 4. Code Pointers
- `web/server.js:61` — `createApp()` wiring runner, store, STS identity and investigation routes
- `web/server.js:116` — concurrent query limit returning `429 ConcurrentQueryLimit`
- `web/runners.js:58` — `LiveRunner` converting BMA events into `progress`, `tool_result` and `answer_delta`
- `web/converse.js:130` — `ConverseRunner` optional backend
- `web/stores.js:76` — `S3Store` history persistence
- `web/office-reports.js:337` — `renderOfficeReport()` DOCX and PPTX export
- `web/build-ui.mjs` — browser bundle build

### 5. Cross-references
- Related modules: `web/`, `webapp/`
- Related ADRs: None yet (use /add-adr)
- Related runbooks: [deploy-production.md](../runbooks/deploy-production.md)
- Related docs: [architecture.md](../architecture.md), [api.md](api.md), [ui.md](ui.md), [agent-llm.md](agent-llm.md), [api-reference.md](../api-reference.md), [bma-investigations.md](../bma-investigations.md), [extraction-reports.md](../extraction-reports.md)

<a id="korean"></a>
## 한국어

### 1. 개요
프론트엔드 계층은 `web/`의 Node.js 24 Web Function입니다. 의존성이 적은 `node:http` 서버가 `/api/*`를 인증하고, STS로 배포 계정을 확인하고, BMA(또는 선택형 Converse 백엔드)를 호출하고, Server-Sent Events를 스트리밍하고, 결과를 S3에 저장하며 Markdown, HTML, DOCX, PPTX 보고서를 생성합니다. 브라우저 번들은 `web/ui/`의 React 19 앱이며 esbuild가 `webapp/static/app.js`로 빌드합니다. Lambda Web Functions가 Node.js 24만 실행하기 때문에 존재하며, Python `webapp/`은 로컬 참조 구현입니다.

### 2. 구성요소
| 구성요소 | 경로 | 목적 |
|---|---|---|
| HTTP server | `web/server.js` | 정적 파일, `/health`, `/api/context`, `/api/chat` SSE, `/api/runs*` 이력과 보고서, bearer 인증과 보안 헤더 |
| Entry and settings | `web/index.js`, `web/settings.js` | `AWS_LAMBDA_HTTP_ENDPOINT`(기본 `127.0.0.1:3000`)에서 대기하고 시작 시 환경 설정을 검증 |
| Agent runners | `web/runners.js`, `web/bma.js`, `web/converse.js` | `SampleRunner` fixture, SigV4 서명 BMA 클라이언트 위의 `LiveRunner`, `RuntimeMcp`를 쓰는 선택형 `ConverseRunner` |
| Result stores | `web/stores.js`, `web/history.js` | `MemoryStore`(샘플)와 `S3Store`(실제), 이력 인덱스, 레코드 크기 한도와 검증 |
| Reports | `web/reports.js`, `web/office-reports.js`, `web/report-rendering.js` | Markdown과 HTML 렌더러, 입력·출력·슬라이드 한도를 둔 DOCX(`docx` 9.6.1)와 PPTX(`pptxgenjs` 4.0.1) |
| Investigations | `web/investigations.js`, `web/investigation-routes.js`, `web/investigation-store.js`, `web/investigation-worker.js`, `web/investigation-executor.js`, `web/procedures.js` | 여러 turn의 BMA 운영 조사, 조건부 쓰기 S3 스냅샷, 비동기 worker 호출, 버전이 있는 절차 카탈로그 |
| Browser UI source | `web/ui/app.js`, `web/ui/investigations.js`, `web/ui/history-panel.js`, `web/ui/resource-insights.js`, `web/markdown.js` | React 19 화면, react-markdown 10.1.0 + remark-gfm 4.0.1로 스트리밍 답변 렌더링 |
| UI build | `web/build-ui.mjs` | esbuild 번들(IIFE, ES2022, minify)을 `webapp/static/app.js`로 출력 |
| Tests | `web/tests/*.test.js` | 서버, BMA, Converse, 이력, 운영 조사, 보고서, UI의 `node --test` 테스트 |

### 3. 주요 결정
- 웹 프레임워크 대신 `node:http`를 사용합니다 — Web Function ZIP이 작게 유지되고 모든 라우트, 헤더, 상태 코드가 `web/server.js`에 명시적으로 드러납니다.
- 환경당 `/api/chat` 동시 스트림을 최대 2개로 제한하고 15초마다 heartbeat를 보냅니다 — 180초 turn 예산을 보호하고 유휴 프록시가 SSE 연결을 끊지 않게 합니다.
- Converse 백엔드는 선택 가능하게 두되 사용하지 않습니다(`AGENT_BACKEND=bma`) — `global.openai.gpt-6-luna` 프로파일은 데이터 처리 범위를 바꾸므로 별도로 표시하고 BMA 배포에는 권한을 주지 않습니다(`docs/data-and-scope.md`).
- 운영 조사는 별도 worker Lambda와 S3 스냅샷으로 실행합니다 — 브라우저가 긴 요청을 유지하지 않고도 재접속해 같은 실행을 이어 볼 수 있습니다(`docs/bma-investigations.md`).
- 보고서 미리보기와 다운로드는 저장된 레코드로만 생성합니다 — 보고서를 열어도 모델 추론이나 AWS 조회를 다시 실행하지 않습니다.

### 4. 코드 포인터
- `web/server.js:61` — runner, store, STS identity, 운영 조사 라우트를 연결하는 `createApp()`
- `web/server.js:116` — `429 ConcurrentQueryLimit`을 반환하는 동시 질의 한도
- `web/runners.js:58` — BMA 이벤트를 `progress`, `tool_result`, `answer_delta`로 변환하는 `LiveRunner`
- `web/converse.js:130` — 선택형 백엔드 `ConverseRunner`
- `web/stores.js:76` — 이력을 저장하는 `S3Store`
- `web/office-reports.js:337` — DOCX와 PPTX를 내보내는 `renderOfficeReport()`
- `web/build-ui.mjs` — 브라우저 번들 빌드

### 5. 상호 참조
- 관련 모듈: `web/`, `webapp/`
- 관련 ADR: 아직 없음 (/add-adr 사용)
- 관련 런북: [deploy-production.md](../runbooks/deploy-production.md)
- 관련 문서: [architecture.md](../architecture.md), [api.md](api.md), [ui.md](ui.md), [agent-llm.md](agent-llm.md), [api-reference.md](../api-reference.md), [bma-investigations.md](../bma-investigations.md), [extraction-reports.md](../extraction-reports.md)
