# Agent · LLM / Agent · LLM 구현 상세

<a href="#english"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English"></a>
<a href="#korean"><img src="https://img.shields.io/badge/lang-한국어-red.svg" alt="Korean"></a>

<a id="english"></a>
## English

### 1. Overview
The agent layer turns a natural-language question into read-only AWS queries. The Web Function creates a Bedrock Managed Agents (BMA) session on the `us-east-1` Mantle endpoint with model `openai.gpt-6-luna`, the session's agent reads the four Skills from the AgentCore Runtime and launches the `aws_inventory` MCP server over STDIO (`agent.tools[].transport.type=stdio`), and only the public `agent.session.turn.output_text.delta` text is streamed back. An optional Converse backend reuses the same MCP server through the Runtime bridge.

### 2. Components
| Component | Path | Purpose |
|---|---|---|
| BMA client (Node.js) | `web/bma.js` | `sessionPayload()` with the `seoul_aws` STDIO MCP tool, SigV4 signing for `bedrock-mantle`, SSE parsing, session events and items |
| BMA client (Python reference) | `webapp/bma.py` | Same session payload and SSE parser for the local reference app |
| Event mapping | `web/runners.js` | `LiveRunner` maps BMA events to `progress`, `tool_result` and `answer_delta`; drops reasoning and command output |
| MCP server | `aws_inventory/mcp_server.py`, `aws_inventory/schema.py` | STDIO MCP server exposing the 24 tools registered in `TOOL_SCHEMAS` |
| Skills | `skills/aws-resource-inventory/SKILL.md`, `skills/aws-service-health/SKILL.md`, `skills/aws-security-posture/SKILL.md`, `skills/aws-operations-report/SKILL.md` | Procedure guidance loaded from `/opt/bma/skills` in the Runtime |
| Build contract | `scripts/export_web_contract.py`, `web/contract.json` | Instructions, allowed tools, supported services and Skill SHA-256 values shared by both backends |
| Converse backend (optional) | `web/converse.js` | `ConverseRunner` with `ConverseStreamCommand` on `global.openai.gpt-6-luna`; tool calls relayed through `RuntimeMcp` (`InvokeAgentRuntime`) |
| Runtime bridge | `runtime/mcp_bridge.py` | Bounded HTTP `tools/list` / `tools/call` bridge to the STDIO MCP server for the Converse path |
| Investigations | `web/investigation-worker.js`, `web/investigation-executor.js`, `web/procedures.js` | Async worker that continues one BMA session across turns; four versioned procedures (`inventory`, `service-health`, `security-review`, `operations-report`, version 1.0.0) |

### 3. Key Decisions
- Use BMA with the regional Mantle model `openai.gpt-6-luna` as the default backend (`AGENT_BACKEND=bma`, `MODEL_PROCESSING_SCOPE=app_region`) — model processing stays in `us-east-1`, which the UI states explicitly (`docs/aws-deployment.md`).
- Attach the MCP server as a required STDIO tool with a fixed command, working directory and environment variable names only — the model cannot change tool configuration, and credentials stay in the Runtime credential chain.
- Treat Skills as guidance, not as the security boundary — the read-only guarantee comes from the tool registry and IAM; Skills only shape the procedure and report format.
- Stream only public text deltas and normalized tool results — reasoning, analysis and raw command execution are neither displayed nor stored; Converse signed reasoning blocks stay in request memory only (`docs/data-and-scope.md`).
- Pin procedure versions and their SHA-256 into investigation instructions — a follow-up turn runs under the same approved procedure snapshot, and evidence reused from earlier turns keeps its original observation time (`docs/bma-investigations.md`).

### 4. Code Pointers
- `web/bma.js:12` — `sessionPayload()` building the BMA agent definition
- `web/bma.js:19` — `seoul_aws` MCP tool with `transport.type: "stdio"`
- `web/runners.js:85` — `agent.session.turn.output_text.delta` to `answer_delta`
- `aws_inventory/schema.py:44` — `TOOL_SCHEMAS` registry of 24 tools
- `aws_inventory/mcp_server.py:15` — `create_server()` MCP tool handlers
- `web/converse.js:180` — `ConverseStreamCommand` call in the optional backend
- `web/procedures.js:85` — `procedureInstructions()` with version and SHA-256

### 5. Cross-references
- Related modules: `web/`, `webapp/`, `aws_inventory/`, `skills/`, `runtime/`
- Related ADRs: None yet (use /add-adr)
- Related runbooks: [deploy-production.md](../runbooks/deploy-production.md)
- Related docs: [architecture.md](../architecture.md), [infrastructure.md](infrastructure.md), [security.md](security.md), [bma-investigations.md](../bma-investigations.md), [data-and-scope.md](../data-and-scope.md), [design.md](../design.md)

<a id="korean"></a>
## 한국어

### 1. 개요
에이전트 계층은 자연어 질문을 읽기 전용 AWS 조회로 바꿉니다. Web Function이 `us-east-1` Mantle 엔드포인트에 모델 `openai.gpt-6-luna`로 Bedrock Managed Agents(BMA) 세션을 만들고, 세션의 에이전트가 AgentCore Runtime에서 4개 Skills를 읽고 `aws_inventory` MCP 서버를 STDIO(`agent.tools[].transport.type=stdio`)로 실행합니다. 브라우저에는 공개 `agent.session.turn.output_text.delta` 텍스트만 스트리밍합니다. 선택형 Converse 백엔드는 Runtime bridge를 통해 같은 MCP 서버를 재사용합니다.

### 2. 구성요소
| 구성요소 | 경로 | 목적 |
|---|---|---|
| BMA client (Node.js) | `web/bma.js` | `seoul_aws` STDIO MCP 도구를 포함한 `sessionPayload()`, `bedrock-mantle` SigV4 서명, SSE 파싱, 세션 이벤트와 항목 |
| BMA client (Python reference) | `webapp/bma.py` | 로컬 참조 앱을 위한 같은 세션 payload와 SSE 파서 |
| Event mapping | `web/runners.js` | `LiveRunner`가 BMA 이벤트를 `progress`, `tool_result`, `answer_delta`로 바꾸고 reasoning과 명령 출력은 버림 |
| MCP server | `aws_inventory/mcp_server.py`, `aws_inventory/schema.py` | `TOOL_SCHEMAS`에 등록한 24개 도구를 제공하는 STDIO MCP 서버 |
| Skills | `skills/aws-resource-inventory/SKILL.md`, `skills/aws-service-health/SKILL.md`, `skills/aws-security-posture/SKILL.md`, `skills/aws-operations-report/SKILL.md` | Runtime의 `/opt/bma/skills`에서 읽는 절차 안내 |
| Build contract | `scripts/export_web_contract.py`, `web/contract.json` | 두 백엔드가 공유하는 지침, 허용 도구, 지원 서비스, Skill SHA-256 |
| Converse backend (optional) | `web/converse.js` | `global.openai.gpt-6-luna`에 `ConverseStreamCommand`를 쓰는 `ConverseRunner`, 도구 호출은 `RuntimeMcp`(`InvokeAgentRuntime`)로 중계 |
| Runtime bridge | `runtime/mcp_bridge.py` | Converse 경로용으로 STDIO MCP 서버에 연결하는 제한된 HTTP `tools/list` / `tools/call` bridge |
| Investigations | `web/investigation-worker.js`, `web/investigation-executor.js`, `web/procedures.js` | 하나의 BMA 세션을 여러 turn에 걸쳐 이어 가는 비동기 worker, 버전이 있는 4개 절차(`inventory`, `service-health`, `security-review`, `operations-report`, 버전 1.0.0) |

### 3. 주요 결정
- 기본 백엔드는 리전 Mantle 모델 `openai.gpt-6-luna`를 쓰는 BMA입니다(`AGENT_BACKEND=bma`, `MODEL_PROCESSING_SCOPE=app_region`) — 모델 처리가 `us-east-1`에 머물며 화면에 이를 명시합니다(`docs/aws-deployment.md`).
- MCP 서버는 고정 명령, 작업 디렉터리, 환경 변수 이름만 지정한 필수 STDIO 도구로 연결합니다 — 모델이 도구 설정을 바꿀 수 없고 자격증명은 Runtime의 credential chain에 남습니다.
- Skills는 보안 경계가 아니라 안내로 취급합니다 — 읽기 전용 보장은 도구 레지스트리와 IAM에서 나오며 Skills는 절차와 보고서 형식만 정합니다.
- 공개 텍스트 delta와 정규화된 도구 결과만 스트리밍합니다 — reasoning, analysis, 원문 명령 실행은 표시하거나 저장하지 않으며 Converse의 서명된 reasoning 블록은 요청 메모리에만 둡니다(`docs/data-and-scope.md`).
- 절차 버전과 SHA-256을 운영 조사 지침에 고정합니다 — 후속 turn도 같은 승인 절차 스냅샷으로 실행되고, 이전 turn에서 재사용한 근거는 원래 관측 시각을 유지합니다(`docs/bma-investigations.md`).

### 4. 코드 포인터
- `web/bma.js:12` — BMA 에이전트 정의를 만드는 `sessionPayload()`
- `web/bma.js:19` — `transport.type: "stdio"`를 쓰는 `seoul_aws` MCP 도구
- `web/runners.js:85` — `agent.session.turn.output_text.delta`를 `answer_delta`로 변환
- `aws_inventory/schema.py:44` — 24개 도구의 `TOOL_SCHEMAS` 레지스트리
- `aws_inventory/mcp_server.py:15` — MCP 도구 핸들러를 만드는 `create_server()`
- `web/converse.js:180` — 선택형 백엔드의 `ConverseStreamCommand` 호출
- `web/procedures.js:85` — 버전과 SHA-256을 포함하는 `procedureInstructions()`

### 5. 상호 참조
- 관련 모듈: `web/`, `webapp/`, `aws_inventory/`, `skills/`, `runtime/`
- 관련 ADR: 아직 없음 (/add-adr 사용)
- 관련 런북: [deploy-production.md](../runbooks/deploy-production.md)
- 관련 문서: [architecture.md](../architecture.md), [infrastructure.md](infrastructure.md), [security.md](security.md), [bma-investigations.md](../bma-investigations.md), [data-and-scope.md](../data-and-scope.md), [design.md](../design.md)
