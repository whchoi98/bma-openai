# API Reference

<a href="#english"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English"></a>
<a href="#korean"><img src="https://img.shields.io/badge/lang-한국어-red.svg" alt="Korean"></a>

---

<a id="english"></a>

# English

## Base URL

| Environment | Base URL |
|-------------|----------|
| CloudFront-enabled deployment | `WebUrl` output of the `bma-seoul-inventory` stack; use the CloudFront URL after OAC cutover |
| Local | `http://127.0.0.1:3000` (`AWS_LAMBDA_HTTP_ENDPOINT` overrides host and port) |

The deployed server is `web/server.js` (Node.js 24). `webapp/main.py` is a Python reference app that implements a subset (see [Python Reference App](#python-reference-app)).

## Authentication

Send the shared access key on every `/api/*` request when `APP_ACCESS_TOKEN` is configured:

```http
Authorization: Bearer <APP_ACCESS_TOKEN>
```

- The key is compared in constant time. A missing or wrong key returns `401 {"error": "AuthenticationRequired"}`.
- `/`, `/static/*` and `/health` do not require the key.
- The key is a single shared secret for trusted demo users; there is no per-user identity.
- After OAC cutover, CloudFront signs origin requests without replacing this header. Direct requests to `OriginWebUrl` return `403`, including requests carrying a valid application key.

## Common Behavior

- Request bodies are JSON and limited to 16,384 bytes (`413 RequestTooLarge`). Unknown body keys are rejected.
- Context, chat, history and investigation endpoints call STS before doing work. A different account returns `409 AccountMismatch`; an STS failure returns `503 AccountVerificationFailed`. Report export reads the stored record without an STS call.
- Errors are JSON `{"error": "<Code>"}` with a named code only. Raw AWS or model error text is never returned.
- APIs, streams, downloads, health responses and errors carry `cache-control: no-store`. Public static files use the bounded cache policy below. Security headers include `x-content-type-options: nosniff`, `referrer-policy: no-referrer` and the application's `content-security-policy`.
- JSON responses for runs and investigations contain the full 12-digit account ID. Rendered reports (Markdown, HTML, DOCX, PPTX) mask it to the last 3 digits.

## Endpoints

### Static and Health

| Method | Path | Response |
|--------|------|----------|
| `GET`, `HEAD` | `/` | `index.html`; `HEAD` returns headers only |
| `GET`, `HEAD` | `/static/style.css`, `/static/report.css`, `/static/app.js` | Page assets |
| `GET`, `HEAD` | `/static/fonts/NanumSquareB.otf`, `/static/fonts/OFL.txt` | Local font and its license |
| `GET` | `/health` | `200 {"status": "ok"}` |

Both apps return `Vary: Authorization, Cookie` on static responses. Anonymous `/` responses use
`Cache-Control: public, max-age=0, s-maxage=60, must-revalidate`; anonymous static assets use
`public, max-age=300, s-maxage=3600, must-revalidate`. A static request carrying `Authorization`
or `Cookie` gets `no-store`. `HEAD` includes the same content type and content length as `GET`,
with no body. Missing files and unsupported routes remain uncacheable.

CloudFront's private cache behavior has minimum/default/maximum TTL zero. Its inline
`ForwardedValues` preserves Authorization, required upload/SSE headers, cookies and query strings
without forwarding the viewer Host. The origin also sends `no-store`; a positive private-path
TTL must not be introduced. See
[CloudFront OAC runbook](runbooks/cloudfront-oac.md).

### Context

```http
GET /api/context
```

**Response** `200 OK`

| Field | Type | Description |
|-------|------|-------------|
| `account_id` | string | Account verified by the Web Function STS call (fixture account in sample mode) |
| `app_region` | string | `us-east-1` |
| `target_region` | string | `ap-northeast-2` |
| `mode` | string | `live` or `sample` |
| `account_source` | string | `web_function_sts` or `synthetic_fixture` |
| `runtime_account_verified` | boolean | Always `false`; the Runtime verifies its own account per tool call |
| `observed_at` | string | ISO 8601 UTC time of this response |
| `supported_services` | string[] | Service categories from `web/contract.json` |
| `lambda_scope` | string | `event_functions_only` |
| `max_resources` | integer | Per-tool resource limit |
| `max_metric_hours` | integer | Metric window limit |
| `model` | string or null | Model ID in live mode, `null` in sample mode |
| `agent_backend` | string | `bma` or `converse` |
| `model_processing_scope` | string | `app_region` for BMA, `global` for Converse |

### Chat (SSE)

```http
POST /api/chat
Content-Type: application/json
```

**Request Body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `prompt` | string | Yes | 1-4,000 characters, not blank; trimmed |
| `language` | string | No | `ko` (default) or `en` |

**Response** `200 OK`, `content-type: text/event-stream`. Each event is one `data: <JSON>` line followed by a blank line.

| Event `type` | Fields | When |
|--------------|--------|------|
| `started` | `id`, `prompt`, `language`, `mode`, `created_at`, `account_id`, `app_region`, `target_region`, `supported_services` | First event |
| `heartbeat` | none | Every 15 seconds |
| `progress` | `message` | Agent connection, query and result preparation steps |
| `tool_result` | `result` | One normalized MCP tool result |
| `answer_delta` | `delta`, `sequence` | Public answer text chunk |
| `complete` | Saved run record without `bma_session_id`, plus `report_available` | Final answer stored |
| `error` | `code`, `id` | Stream failed; `code` is a named BMA client code or `AppExecutionError` |

If the record cannot be saved, `complete` still arrives with `status: "partial"` and `ReportPersistenceFailed` or `HistoryIndexWriteFailed` in `errors`.

```bash
curl -N -X POST "$BASE_URL/api/chat" \
  -H "Authorization: Bearer $APP_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "List EC2 instances in Seoul", "language": "en"}'
```

### Run History

```http
GET /api/runs?limit=10&cursor=<next_cursor>
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `limit` | integer | No | 1-20 (default 10) |
| `cursor` | string | No | `next_cursor` from the previous page |

**Response** `200 OK` `{"runs": [...], "next_cursor": "<string or null>", "complete": <boolean>}`

```http
GET /api/runs/{run_id}
```

`run_id` is a lowercase UUID. **Response** `200 OK` with the saved record without `bma_session_id`, plus `report_available`.

### Report Export

```http
GET /api/runs/{run_id}/report.{md|html|docx|pptx}?view=&theme=
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `view` | string | No | `preview` (inline) or `download`; only valid with `html` |
| `theme` | string | No | `light` (default) or `dark` |

**Response** `200 OK` with `text/markdown`, `text/html`, or the Office MIME type. `preview` is served `inline`; every other response is an `attachment` named `aws-report-<run_id>.<format>`. Reports are rendered from the stored record and never repeat model inference or AWS queries.

### Procedures

```http
GET /api/procedures
```

**Response** `200 OK` `{"procedures": [...], "enabled": <boolean>}`. Procedures are `inventory`, `service-health`, `security-review` and `operations-report`, each version `1.0.0` with steps and an SHA-256.

### Investigations

Investigations run asynchronously in a worker Lambda and keep one BMA session across turns. They are enabled in sample mode, or in live mode with `AGENT_BACKEND=bma` and `INVESTIGATION_WORKER_ARN`; otherwise they return `503 InvestigationsUnavailable`. Limits: 10 turns and 6 hours per investigation. Query parameters are accepted only on the list endpoint.

| Method | Path | Body | Success |
|--------|------|------|---------|
| `GET` | `/api/investigations?limit=&cursor=` | none | `200 {"investigations": [...], "next_cursor": ..., "complete": ...}` |
| `POST` | `/api/investigations` | `request_id`, `procedure_id`, `prompt`, `language` | `202 {"investigation": {...}, "run": {...}}` |
| `GET` | `/api/investigations/{id}` | none | `200 {"investigation": {...}, "run": {...}}` (active or latest turn) |
| `POST` | `/api/investigations/{id}/turns` | `request_id`, `prompt`, `language` | `202 {"investigation": {...}, "run": {...}}` |
| `GET` | `/api/investigations/{id}/turns/{run_id}` | none | `200 {"investigation": {...}, "run": {...}}` |
| `GET` | `/api/investigations/{id}/turns/{run_id}/events` | none | `200` SSE stream |
| `POST` | `/api/investigations/{id}/turns/{run_id}/cancel` | `{}` | `202 {"investigation": {...}, "run": {...}}` |

**Request Body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `request_id` | string | Yes | Client-generated UUID; becomes the investigation ID on create and the run ID on each turn. Retrying with the same input is idempotent |
| `procedure_id` | string | Create only | One of the IDs from `/api/procedures` |
| `prompt` | string | Yes | 1-4,000 characters, not blank; trimmed |
| `language` | string | No | `ko` (default) or `en` |

List parameters: `limit` 1-20 (default 10); `cursor` matches `[A-Za-z0-9_-]{1,4096}`.

**Turn Events (SSE)**

| Event `type` | Fields | When |
|--------------|--------|------|
| `snapshot` | `investigation`, `run` | Stored state changed |
| `heartbeat` | none | Every 10 polls without change |
| `complete` | Public report fields | Turn finished with a result |
| `error` | `code` | Named investigation error code |

The stream ends after 360 seconds; reconnect with the same URL to resume from stored state.

## Error Codes

| Code | Error | Description |
|------|-------|-------------|
| 400 | `InvalidJson` | Body is not valid JSON |
| 400 | `InvalidHistoryRequest`, `InvalidHistoryLimit`, `InvalidHistoryCursor` | Unknown history parameter, or invalid `limit` or `cursor` |
| 400 | `InvalidReportView` | Invalid `view` or `theme`, or `view` on a non-HTML format |
| 400 | `InvalidInvestigationRequest`, `InvalidInvestigationLimit`, `InvalidInvestigationCursor` | Unexpected or invalid investigation query parameter |
| 401 | `AuthenticationRequired` | Missing or wrong bearer key |
| 404 | `NotFound`, `ReportNotFound`, `InvestigationNotFound` | Unknown path, run or investigation |
| 405 | `MethodNotAllowed` | Wrong method on an investigation route; `allow` header lists valid methods |
| 409 | `AccountMismatch` | STS account differs from `EXPECTED_ACCOUNT_ID` |
| 409 | `InvestigationBusy`, `InvestigationActive`, `InvestigationConflict` | A turn is already running or a concurrent write conflicted |
| 409 | `InvestigationTurnLimit`, `InvestigationConfigurationChanged`, `RequestIdConflict` | 10-turn limit reached, model or Runtime changed, or `request_id` reused with different input |
| 410 | `InvestigationExpired` | Investigation is older than 6 hours |
| 413 | `RequestTooLarge`, `OfficeReportTooLarge` | Body over 16,384 bytes, or Office export over its size limits |
| 422 | `InvalidInput`, `InvalidLanguage` | Invalid chat body or language |
| 422 | `InvalidInvestigationId`, `InvalidInvestigationInput`, `InvalidProcedure`, `UnknownProcedure` | Invalid investigation ID, body or procedure |
| 429 | `ConcurrentQueryLimit` | Two chat streams are already active |
| 500 | `AppExecutionError`, `OfficeExportFailed` | Unexpected server error, or DOCX/PPTX rendering failed |
| 503 | `AccountVerificationFailed` | STS call failed |
| 503 | `HistoryReadFailed`, `ReportReadFailed` | S3 read failed |
| 503 | `InvestigationsUnavailable`, `InvestigationUnavailable`, `InvestigationDispatchFailed`, `WorkerDispatchFailed`, `InvestigationReadFailed`, `InvestigationIndexWriteFailed`, `InvalidInvestigationRecord` | Investigations disabled, worker dispatch failed, or state could not be read or written |

## Rate Limits

| Limit | Value | Source |
|-------|-------|--------|
| Endpoint request rate | 100 requests per second | `WebEndpoint.ThrottleConfig` in `infra/template.yaml` |
| Web environments | Up to 2, 8 concurrent requests each | `WebEndpoint.ScalingConfig`, `WebRevision.ServiceConfig` |
| Concurrent chat streams | 2 per server instance | `web/server.js` |
| Concurrent investigation workers | 2 | `InvestigationWorker.ReservedConcurrentExecutions` |
| Agent turn time | `MAX_TURN_SECONDS` (default 180, deployed 300) | `web/settings.js` |

## AI Document Studio API

A separate server, `studio/web/server.js`, on the `WebUrl` of the `bma-office-studio` stack. All `/api/*` paths need `Authorization: Bearer <APP_ACCESS_TOKEN>`; the STS account is checked after authentication (`409 {"error":"AccountMismatch"}`). Full request and job shapes: [studio/README.md](../studio/README.md#web-api).

Studio uses the same static GET/HEAD and cache rules above, with no `/static/report.css` route.
Uploads, job snapshots, SSE, file downloads and inline HTML previews all use `no-store`.

| Method and path | Request | Response |
|-----------------|---------|----------|
| `GET /api/config` | - | `{model, app_region, styles, limits, formats}` |
| `POST /api/uploads` | Raw body (`application/octet-stream`), `X-File-Name: encodeURIComponent(name)`; `.xlsx`, `.csv`, `.txt`, `.md`, up to 5 MiB | `201 {upload: {id, name, size, extension}}` |
| `POST /api/jobs` | `{request_id, upload_id?, notes?, prompt, outputs, style, language, source_job_id?}`; `outputs` from `pptx`, `docx`, `chart`, `diagram` | `202 {job}`; the same `request_id` returns the same job |
| `GET /api/jobs?limit=10&cursor=` | - | `{jobs, next_cursor, complete}` |
| `GET /api/jobs/{id}` | - | `{job}` |
| `GET /api/jobs/{id}/events` | - | SSE `{type: "snapshot"\|"heartbeat"\|"complete", job}`; errors `{type: "error", code}` |
| `POST /api/jobs/{id}/cancel` | Empty JSON object `{}` | `202 {job}` |
| `GET /api/jobs/{id}/artifacts/{artifact_id}[?view=inline]` | - | File bytes; `inline` only for PNG, SVG and HTML, with a `sandbox` CSP |

Job `status` is `queued`, `running`, `complete`, `partial`, `failed`, `cancelled` or `uncertain`; `phase` is `queued`, `reading`, `analyzing`, `charting`, `diagramming`, `writing`, `packaging` or `done`. Public jobs never include BMA session IDs, S3 keys or credentials. Validation errors return `422 {"error":"<Code>"}` (for example `UnsupportedFile`, `InvalidOutputs`, `NotesTooLong`); `413 FileTooLarge`, `404 JobNotFound`/`ArtifactNotFound`, `409 RequestIdConflict` and `503 WorkerUnavailable` are the other stable codes.

## Python Reference App

`webapp/main.py` (FastAPI, `bma-inventory-web`) implements `GET /`, `GET /health`, `GET /api/context`, `POST /api/chat` and `GET /api/runs/{run_id}/report.{md|html}` with the same bearer check (`hmac.compare_digest`), 16,384-byte POST limit and security headers. Its `/api/context` omits `agent_backend` and `model_processing_scope`, and history, Office export and investigations are not implemented. Use it for local verification only; the deployed API is `web/server.js`.

---

<a id="korean"></a>

# 한국어

## Base URL

| 환경 | Base URL |
|------|----------|
| CloudFront 구성 배포 | `bma-seoul-inventory` 스택의 `WebUrl` 출력. OAC 전환 뒤에는 CloudFront 주소를 사용합니다 |
| 로컬 | `http://127.0.0.1:3000`(`AWS_LAMBDA_HTTP_ENDPOINT`로 호스트와 포트 변경) |

배포 서버는 `web/server.js`(Node.js 24)입니다. `webapp/main.py`는 일부 기능만 구현한 Python 참조 앱입니다([Python 참조 앱](#python-참조-앱) 참고).

## 인증

`APP_ACCESS_TOKEN`이 설정되어 있으면 모든 `/api/*` 요청에 공유 접속 키를 보냅니다.

```http
Authorization: Bearer <APP_ACCESS_TOKEN>
```

- 키는 상수 시간으로 비교합니다. 키가 없거나 다르면 `401 {"error": "AuthenticationRequired"}`를 반환합니다.
- `/`, `/static/*`, `/health`에는 키가 필요하지 않습니다.
- 신뢰된 데모 사용자를 위한 공유 비밀 하나이며 사용자별 인증은 없습니다.
- OAC 전환 뒤에는 CloudFront가 이 헤더를 유지한 채 오리진 요청을 서명합니다. `OriginWebUrl` 직접 요청은 올바른 앱 이용 키가 있어도 `403`으로 거부됩니다.

## 공통 동작

- 요청 본문은 JSON이며 16,384바이트로 제한합니다(`413 RequestTooLarge`). 알 수 없는 본문 키는 거부합니다.
- 컨텍스트, 채팅, 이력, 운영 조사 엔드포인트는 작업 전에 STS를 호출합니다. 계정이 다르면 `409 AccountMismatch`, STS 호출이 실패하면 `503 AccountVerificationFailed`를 반환합니다. 보고서 내보내기는 STS 호출 없이 저장된 레코드를 읽습니다.
- 오류는 이름이 정해진 코드만 담은 JSON `{"error": "<Code>"}`입니다. AWS나 모델의 원문 오류는 반환하지 않습니다.
- API, 스트림, 다운로드, 상태 확인, 오류 응답은 `cache-control: no-store`를 사용합니다. 공개 정적 파일은 아래의 제한된 캐시 정책을 사용합니다. 보안 헤더는 `x-content-type-options: nosniff`, `referrer-policy: no-referrer`와 앱의 `content-security-policy`입니다.
- 실행 기록과 운영 조사의 JSON 응답에는 12자리 전체 계정 ID가 들어 있습니다. 렌더링한 보고서(Markdown, HTML, DOCX, PPTX)는 마지막 3자리만 표시합니다.

## 엔드포인트

### 정적 파일과 상태 확인

| Method | Path | Response |
|--------|------|----------|
| `GET`, `HEAD` | `/` | `index.html`. `HEAD`는 헤더만 반환 |
| `GET`, `HEAD` | `/static/style.css`, `/static/report.css`, `/static/app.js` | 화면 자산 |
| `GET`, `HEAD` | `/static/fonts/NanumSquareB.otf`, `/static/fonts/OFL.txt` | 로컬 폰트와 라이선스 |
| `GET` | `/health` | `200 {"status": "ok"}` |

두 앱의 정적 응답은 `Vary: Authorization, Cookie`를 반환합니다. 익명 `/` 응답은
`Cache-Control: public, max-age=0, s-maxage=60, must-revalidate`, 익명 정적 자산은
`public, max-age=300, s-maxage=3600, must-revalidate`를 사용합니다. `Authorization`이나
`Cookie`가 있는 정적 요청은 `no-store`입니다. `HEAD`는 `GET`과 같은 콘텐츠 형식과 길이를
반환하며 본문은 보내지 않습니다. 없는 파일과 지원하지 않는 경로는 캐시하지 않습니다.

CloudFront의 비공개 응답용 캐시 동작은 최소/기본/최대 TTL이 모두 0초입니다.
인라인 `ForwardedValues`는 Authorization, 필요한 업로드/SSE 헤더, 쿠키, 쿼리 문자열을
전달하고 사용자 Host는 전달하지 않습니다. 오리진도 `no-store`를 보내며, 비공개 경로의
TTL을 양수로 바꾸면 안 됩니다.
[CloudFront OAC 운영 절차](runbooks/cloudfront-oac.md)를 참고합니다.

### 컨텍스트

```http
GET /api/context
```

**응답** `200 OK`

| Field | Type | Description |
|-------|------|-------------|
| `account_id` | string | Web Function의 STS 호출로 확인한 계정(샘플 모드에서는 fixture 계정) |
| `app_region` | string | `us-east-1` |
| `target_region` | string | `ap-northeast-2` |
| `mode` | string | `live` 또는 `sample` |
| `account_source` | string | `web_function_sts` 또는 `synthetic_fixture` |
| `runtime_account_verified` | boolean | 항상 `false`이며 Runtime은 도구 호출마다 자체 계정을 확인 |
| `observed_at` | string | 이 응답의 ISO 8601 UTC 시각 |
| `supported_services` | string[] | `web/contract.json`의 서비스 범주 |
| `lambda_scope` | string | `event_functions_only` |
| `max_resources` | integer | 도구당 리소스 한도 |
| `max_metric_hours` | integer | 지표 조회 기간 한도 |
| `model` | string or null | 실제 모드의 모델 ID, 샘플 모드에서는 `null` |
| `agent_backend` | string | `bma` 또는 `converse` |
| `model_processing_scope` | string | BMA는 `app_region`, Converse는 `global` |

### 채팅 (SSE)

```http
POST /api/chat
Content-Type: application/json
```

**요청 본문**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `prompt` | string | Yes | 공백이 아닌 1-4,000자, 앞뒤 공백 제거 |
| `language` | string | No | `ko`(기본값) 또는 `en` |

**응답** `200 OK`, `content-type: text/event-stream`. 각 이벤트는 `data: <JSON>` 한 줄과 빈 줄로 구성됩니다.

| Event `type` | Fields | When |
|--------------|--------|------|
| `started` | `id`, `prompt`, `language`, `mode`, `created_at`, `account_id`, `app_region`, `target_region`, `supported_services` | 첫 이벤트 |
| `heartbeat` | 없음 | 15초마다 |
| `progress` | `message` | 에이전트 연결, 조회, 결과 정리 단계 |
| `tool_result` | `result` | 정규화된 MCP 도구 결과 하나 |
| `answer_delta` | `delta`, `sequence` | 공개 답변 텍스트 조각 |
| `complete` | `bma_session_id`를 제외한 저장 레코드와 `report_available` | 최종 답변 저장 완료 |
| `error` | `code`, `id` | 스트림 실패, `code`는 BMA 클라이언트의 이름 있는 코드 또는 `AppExecutionError` |

레코드를 저장하지 못해도 `complete`는 전달되며, 이때 `status: "partial"`이고 `errors`에 `ReportPersistenceFailed` 또는 `HistoryIndexWriteFailed`가 들어 있습니다.

```bash
curl -N -X POST "$BASE_URL/api/chat" \
  -H "Authorization: Bearer $APP_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "List EC2 instances in Seoul", "language": "en"}'
```

### 실행 이력

```http
GET /api/runs?limit=10&cursor=<next_cursor>
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `limit` | integer | No | 1-20(기본값 10) |
| `cursor` | string | No | 이전 페이지의 `next_cursor` |

**응답** `200 OK` `{"runs": [...], "next_cursor": "<string or null>", "complete": <boolean>}`

```http
GET /api/runs/{run_id}
```

`run_id`는 소문자 UUID입니다. **응답** `200 OK`, `bma_session_id`를 제외한 저장 레코드와 `report_available`.

### 보고서 내보내기

```http
GET /api/runs/{run_id}/report.{md|html|docx|pptx}?view=&theme=
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `view` | string | No | `preview`(inline) 또는 `download`, `html`에서만 사용 가능 |
| `theme` | string | No | `light`(기본값) 또는 `dark` |

**응답** `200 OK`, `text/markdown`, `text/html` 또는 Office MIME 형식. `preview`는 `inline`으로, 나머지는 `aws-report-<run_id>.<format>` 이름의 `attachment`로 제공합니다. 보고서는 저장된 레코드로 렌더링하며 모델 추론이나 AWS 조회를 다시 실행하지 않습니다.

### 절차

```http
GET /api/procedures
```

**응답** `200 OK` `{"procedures": [...], "enabled": <boolean>}`. 절차는 `inventory`, `service-health`, `security-review`, `operations-report`이며 모두 버전 `1.0.0`과 단계, SHA-256을 갖습니다.

### 운영 조사

운영 조사는 worker Lambda에서 비동기로 실행되며 여러 turn에 걸쳐 하나의 BMA 세션을 유지합니다. 샘플 모드, 또는 `AGENT_BACKEND=bma`와 `INVESTIGATION_WORKER_ARN`이 설정된 실제 모드에서 사용할 수 있으며 그 외에는 `503 InvestigationsUnavailable`을 반환합니다. 조사 하나당 10개 turn, 6시간으로 제한합니다. 쿼리 파라미터는 목록 엔드포인트에서만 받습니다.

| Method | Path | Body | Success |
|--------|------|------|---------|
| `GET` | `/api/investigations?limit=&cursor=` | 없음 | `200 {"investigations": [...], "next_cursor": ..., "complete": ...}` |
| `POST` | `/api/investigations` | `request_id`, `procedure_id`, `prompt`, `language` | `202 {"investigation": {...}, "run": {...}}` |
| `GET` | `/api/investigations/{id}` | 없음 | `200 {"investigation": {...}, "run": {...}}`(진행 중 또는 마지막 turn) |
| `POST` | `/api/investigations/{id}/turns` | `request_id`, `prompt`, `language` | `202 {"investigation": {...}, "run": {...}}` |
| `GET` | `/api/investigations/{id}/turns/{run_id}` | 없음 | `200 {"investigation": {...}, "run": {...}}` |
| `GET` | `/api/investigations/{id}/turns/{run_id}/events` | 없음 | `200` SSE 스트림 |
| `POST` | `/api/investigations/{id}/turns/{run_id}/cancel` | `{}` | `202 {"investigation": {...}, "run": {...}}` |

**요청 본문**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `request_id` | string | Yes | 클라이언트가 만든 UUID, 생성 시 조사 ID이자 각 turn의 실행 ID가 되며 같은 입력의 재시도는 멱등 |
| `procedure_id` | string | 생성 시만 | `/api/procedures`의 ID 중 하나 |
| `prompt` | string | Yes | 공백이 아닌 1-4,000자, 앞뒤 공백 제거 |
| `language` | string | No | `ko`(기본값) 또는 `en` |

목록 파라미터: `limit`은 1-20(기본값 10), `cursor`는 `[A-Za-z0-9_-]{1,4096}`과 일치해야 합니다.

**Turn 이벤트 (SSE)**

| Event `type` | Fields | When |
|--------------|--------|------|
| `snapshot` | `investigation`, `run` | 저장된 상태가 바뀜 |
| `heartbeat` | 없음 | 변화 없이 10회 조회할 때마다 |
| `complete` | 공개 보고서 필드 | 결과와 함께 turn 완료 |
| `error` | `code` | 이름 있는 운영 조사 오류 코드 |

스트림은 360초 후 종료됩니다. 같은 URL로 다시 연결하면 저장된 상태부터 이어서 받습니다.

## 오류 코드

| Code | Error | Description |
|------|-------|-------------|
| 400 | `InvalidJson` | 본문이 올바른 JSON이 아님 |
| 400 | `InvalidHistoryRequest`, `InvalidHistoryLimit`, `InvalidHistoryCursor` | 알 수 없는 이력 파라미터 또는 잘못된 `limit`, `cursor` |
| 400 | `InvalidReportView` | 잘못된 `view`, `theme`, 또는 HTML이 아닌 형식에 `view` 지정 |
| 400 | `InvalidInvestigationRequest`, `InvalidInvestigationLimit`, `InvalidInvestigationCursor` | 예상하지 않았거나 잘못된 운영 조사 쿼리 파라미터 |
| 401 | `AuthenticationRequired` | bearer 키가 없거나 다름 |
| 404 | `NotFound`, `ReportNotFound`, `InvestigationNotFound` | 알 수 없는 경로, 실행 기록, 운영 조사 |
| 405 | `MethodNotAllowed` | 운영 조사 라우트의 잘못된 메서드, `allow` 헤더에 허용 메서드 표시 |
| 409 | `AccountMismatch` | STS 계정이 `EXPECTED_ACCOUNT_ID`와 다름 |
| 409 | `InvestigationBusy`, `InvestigationActive`, `InvestigationConflict` | 이미 실행 중인 turn이 있거나 동시 쓰기가 충돌함 |
| 409 | `InvestigationTurnLimit`, `InvestigationConfigurationChanged`, `RequestIdConflict` | 10개 turn 한도 도달, 모델 또는 Runtime 변경, 다른 입력으로 `request_id` 재사용 |
| 410 | `InvestigationExpired` | 생성 후 6시간이 지난 운영 조사 |
| 413 | `RequestTooLarge`, `OfficeReportTooLarge` | 본문이 16,384바이트 초과, 또는 Office 내보내기 크기 한도 초과 |
| 422 | `InvalidInput`, `InvalidLanguage` | 잘못된 채팅 본문 또는 언어 |
| 422 | `InvalidInvestigationId`, `InvalidInvestigationInput`, `InvalidProcedure`, `UnknownProcedure` | 잘못된 운영 조사 ID, 본문, 절차 |
| 429 | `ConcurrentQueryLimit` | 이미 채팅 스트림 2개가 실행 중 |
| 500 | `AppExecutionError`, `OfficeExportFailed` | 예상하지 못한 서버 오류 또는 DOCX/PPTX 렌더링 실패 |
| 503 | `AccountVerificationFailed` | STS 호출 실패 |
| 503 | `HistoryReadFailed`, `ReportReadFailed` | S3 읽기 실패 |
| 503 | `InvestigationsUnavailable`, `InvestigationUnavailable`, `InvestigationDispatchFailed`, `WorkerDispatchFailed`, `InvestigationReadFailed`, `InvestigationIndexWriteFailed`, `InvalidInvestigationRecord` | 운영 조사 비활성화, worker 호출 실패, 상태 읽기 또는 쓰기 실패 |

## 요청 한도

| Limit | Value | Source |
|-------|-------|--------|
| Endpoint 요청 속도 | 초당 100건 | `infra/template.yaml`의 `WebEndpoint.ThrottleConfig` |
| Web 환경 | 최대 2개, 환경당 동시 요청 8건 | `WebEndpoint.ScalingConfig`, `WebRevision.ServiceConfig` |
| 동시 채팅 스트림 | 서버 인스턴스당 2개 | `web/server.js` |
| 동시 운영 조사 worker | 2개 | `InvestigationWorker.ReservedConcurrentExecutions` |
| 에이전트 turn 시간 | `MAX_TURN_SECONDS`(기본 180, 현재 배포 300) | `web/settings.js` |

## AI Document Studio API

별도 서버인 `studio/web/server.js`가 `bma-office-studio` 스택의 `WebUrl`에서 동작합니다. 모든 `/api/*` 경로에 `Authorization: Bearer <APP_ACCESS_TOKEN>`이 필요하며, 인증 뒤 STS 계정을 확인합니다(`409 {"error":"AccountMismatch"}`). 요청과 작업의 전체 형식은 [studio/README.md](../studio/README.md#web-api)를 참고합니다.

Studio도 위의 정적 GET/HEAD와 캐시 규칙을 사용하지만 `/static/report.css`는 제공하지 않습니다.
업로드, 작업 스냅샷, SSE, 파일 다운로드, HTML 미리보기는 모두 `no-store`입니다.

| Method and path | Request | Response |
|-----------------|---------|----------|
| `GET /api/config` | - | `{model, app_region, styles, limits, formats}` |
| `POST /api/uploads` | 원본 body(`application/octet-stream`), `X-File-Name: encodeURIComponent(name)`, `.xlsx`, `.csv`, `.txt`, `.md`, 최대 5 MiB | `201 {upload: {id, name, size, extension}}` |
| `POST /api/jobs` | `{request_id, upload_id?, notes?, prompt, outputs, style, language, source_job_id?}`, `outputs`는 `pptx`, `docx`, `chart`, `diagram` 중 선택 | `202 {job}`, 같은 `request_id`는 같은 작업을 반환 |
| `GET /api/jobs?limit=10&cursor=` | - | `{jobs, next_cursor, complete}` |
| `GET /api/jobs/{id}` | - | `{job}` |
| `GET /api/jobs/{id}/events` | - | SSE `{type: "snapshot"\|"heartbeat"\|"complete", job}`, 오류는 `{type: "error", code}` |
| `POST /api/jobs/{id}/cancel` | 빈 JSON 객체 `{}` | `202 {job}` |
| `GET /api/jobs/{id}/artifacts/{artifact_id}[?view=inline]` | - | 파일 바이트, `inline`은 PNG, SVG, HTML에만 `sandbox` CSP와 함께 적용 |

작업 `status`는 `queued`, `running`, `complete`, `partial`, `failed`, `cancelled`, `uncertain`이고 `phase`는 `queued`, `reading`, `analyzing`, `charting`, `diagramming`, `writing`, `packaging`, `done`입니다. 공개 작업 정보에는 BMA 세션 ID, S3 key, 자격증명이 포함되지 않습니다. 검증 오류는 `422 {"error":"<Code>"}`(예: `UnsupportedFile`, `InvalidOutputs`, `NotesTooLong`)를 반환하며, 그 밖의 고정 코드는 `413 FileTooLarge`, `404 JobNotFound`/`ArtifactNotFound`, `409 RequestIdConflict`, `503 WorkerUnavailable`입니다.

## Python 참조 앱

`webapp/main.py`(FastAPI, `bma-inventory-web`)는 `GET /`, `GET /health`, `GET /api/context`, `POST /api/chat`, `GET /api/runs/{run_id}/report.{md|html}`를 구현하며 같은 bearer 검사(`hmac.compare_digest`), 16,384바이트 POST 한도, 보안 헤더를 적용합니다. `/api/context`에는 `agent_backend`와 `model_processing_scope`가 없고 이력, Office 내보내기, 운영 조사는 구현하지 않았습니다. 로컬 검증에만 사용하며 배포 API는 `web/server.js`입니다.
