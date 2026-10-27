# API / API 구성 상세

<a href="#english"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English"></a>
<a href="#korean"><img src="https://img.shields.io/badge/lang-한국어-red.svg" alt="Korean"></a>

<a id="english"></a>
## English

### 1. Overview
The API layer is the HTTP surface of the Web Function: JSON endpoints for context, history, reports, procedures and investigations, and two Server-Sent Events streams (`POST /api/chat` and investigation turn events). Every `/api/*` request is authenticated with the shared bearer key; context, chat, history and investigation endpoints also re-verify the deployment account with STS before doing work, while report export reads the stored record without an STS call. The full endpoint list, request fields and error codes are in [api-reference.md](../api-reference.md).

### 2. Components
| Component | Path | Purpose |
|---|---|---|
| Core routes | `web/server.js` | `/`, `/static/*`, `/health`, `/api/context`, `/api/chat`, `/api/runs`, `/api/runs/{id}`, `/api/runs/{id}/report.{md,html,docx,pptx}` |
| Investigation routes | `web/investigation-routes.js` | `/api/procedures`, `/api/investigations`, `/api/investigations/{id}[/turns[/{runId}[/events or /cancel]]]`; method checks and public error mapping |
| Input validation | `web/investigation-records.js` | `validateInvestigationId()` (UUID) and `validateInvestigationInput()` (`request_id`, `procedure_id`, `prompt`, `language`) |
| Investigation service | `web/investigations.js` | `catalog`, `list`, `create`, `get`, `submit`, `cancel`, `stream` behind the routes |
| Python reference subset | `webapp/main.py` | FastAPI app with `/`, `/health`, `/api/context`, `/api/chat`, `/api/runs/{id}/report.{md,html}` for local verification |
| Route tests | `web/tests/app.test.js`, `web/tests/investigation-routes.test.js`, `web/tests/investigation-server.test.js`, `tests/test_web.py` | Status codes, auth, SSE framing, body limits and error mapping |

### 3. Key Decisions
- Stream chat answers as SSE on the `POST` response and keep everything else JSON — the browser renders partial Markdown as `answer_delta` events arrive, and a 15 s heartbeat keeps the stream open.
- Reject unknown body keys and query parameters with 400 or 422 instead of ignoring them — clients cannot smuggle extra fields, and the contract stays testable.
- Return only named error codes; map unknown failures to `AppExecutionError` or `InvestigationUnavailable` — raw AWS or model error text never reaches the browser.
- Use a client-generated UUID `request_id` for investigation create and follow-up turns, answered with `202 Accepted` — retries are idempotent, and a reused ID with different input returns `RequestIdConflict`.
- Verify the account on each context, chat, history and investigation call (`409 AccountMismatch`, `503 AccountVerificationFailed`) — a credential change after deployment stops the API instead of serving another account.

### 4. Code Pointers
- `web/server.js:90` — bearer authentication for `/api/*`
- `web/server.js:113` — `POST /api/chat` SSE handler
- `web/server.js:150` — `GET /api/runs` pagination with `limit` and `cursor`
- `web/server.js:178` — report export route for `md`, `html`, `docx`, `pptx`
- `web/investigation-routes.js:19` — `publicInvestigationError()` public error mapping
- `web/investigation-routes.js:96` — `createInvestigationRoutes()` dispatcher
- `web/investigation-records.js:62` — `validateInvestigationInput()`

### 5. Cross-references
- Related modules: `web/`, `webapp/`
- Related ADRs: None yet (use /add-adr)
- Related runbooks: [deploy-production.md](../runbooks/deploy-production.md)
- Related docs: [api-reference.md](../api-reference.md), [architecture.md](../architecture.md), [frontend.md](frontend.md), [security.md](security.md), [bma-investigations.md](../bma-investigations.md)

<a id="korean"></a>
## 한국어

### 1. 개요
API 계층은 Web Function의 HTTP 인터페이스입니다. 컨텍스트, 이력, 보고서, 절차, 운영 조사를 위한 JSON 엔드포인트와 두 개의 Server-Sent Events 스트림(`POST /api/chat`, 운영 조사 turn 이벤트)을 제공합니다. 모든 `/api/*` 요청은 공유 bearer 키로 인증합니다. 컨텍스트, 채팅, 이력, 운영 조사 엔드포인트는 작업 전에 STS로 배포 계정도 다시 확인하며, 보고서 내보내기는 STS 호출 없이 저장된 레코드를 읽습니다. 전체 엔드포인트, 요청 필드, 오류 코드는 [api-reference.md](../api-reference.md)에 있습니다.

### 2. 구성요소
| 구성요소 | 경로 | 목적 |
|---|---|---|
| Core routes | `web/server.js` | `/`, `/static/*`, `/health`, `/api/context`, `/api/chat`, `/api/runs`, `/api/runs/{id}`, `/api/runs/{id}/report.{md,html,docx,pptx}` |
| Investigation routes | `web/investigation-routes.js` | `/api/procedures`, `/api/investigations`, `/api/investigations/{id}[/turns[/{runId}[/events 또는 /cancel]]]`, 메서드 검사와 공개 오류 매핑 |
| Input validation | `web/investigation-records.js` | `validateInvestigationId()`(UUID)와 `validateInvestigationInput()`(`request_id`, `procedure_id`, `prompt`, `language`) |
| Investigation service | `web/investigations.js` | 라우트 뒤의 `catalog`, `list`, `create`, `get`, `submit`, `cancel`, `stream` |
| Python reference subset | `webapp/main.py` | 로컬 검증용 FastAPI 앱: `/`, `/health`, `/api/context`, `/api/chat`, `/api/runs/{id}/report.{md,html}` |
| Route tests | `web/tests/app.test.js`, `web/tests/investigation-routes.test.js`, `web/tests/investigation-server.test.js`, `tests/test_web.py` | 상태 코드, 인증, SSE 형식, 본문 한도, 오류 매핑 |

### 3. 주요 결정
- 채팅 답변은 `POST` 응답의 SSE로 스트리밍하고 나머지는 JSON으로 유지합니다 — `answer_delta` 이벤트가 오는 대로 브라우저가 부분 Markdown을 렌더링하고, 15초 heartbeat가 스트림을 유지합니다.
- 알 수 없는 본문 키와 쿼리 파라미터는 무시하지 않고 400 또는 422로 거부합니다 — 클라이언트가 추가 필드를 끼워 넣을 수 없고 계약을 테스트로 검증할 수 있습니다.
- 이름이 정해진 오류 코드만 반환하고 알 수 없는 실패는 `AppExecutionError` 또는 `InvestigationUnavailable`로 바꿉니다 — AWS나 모델의 원문 오류가 브라우저에 전달되지 않습니다.
- 운영 조사 생성과 후속 turn에는 클라이언트가 만든 UUID `request_id`를 쓰고 `202 Accepted`로 응답합니다 — 재시도가 멱등이며, 같은 ID를 다른 입력으로 다시 쓰면 `RequestIdConflict`를 반환합니다.
- 컨텍스트, 채팅, 이력, 운영 조사 호출마다 계정을 확인합니다(`409 AccountMismatch`, `503 AccountVerificationFailed`) — 배포 후 자격증명이 바뀌면 다른 계정을 제공하지 않고 API가 멈춥니다.

### 4. 코드 포인터
- `web/server.js:90` — `/api/*` bearer 인증
- `web/server.js:113` — `POST /api/chat` SSE 핸들러
- `web/server.js:150` — `limit`, `cursor`를 쓰는 `GET /api/runs` 페이지 처리
- `web/server.js:178` — `md`, `html`, `docx`, `pptx` 보고서 내보내기 라우트
- `web/investigation-routes.js:19` — 공개 오류를 매핑하는 `publicInvestigationError()`
- `web/investigation-routes.js:96` — `createInvestigationRoutes()` 디스패처
- `web/investigation-records.js:62` — `validateInvestigationInput()`

### 5. 상호 참조
- 관련 모듈: `web/`, `webapp/`
- 관련 ADR: 아직 없음 (/add-adr 사용)
- 관련 런북: [deploy-production.md](../runbooks/deploy-production.md)
- 관련 문서: [api-reference.md](../api-reference.md), [architecture.md](../architecture.md), [frontend.md](frontend.md), [security.md](security.md), [bma-investigations.md](../bma-investigations.md)
