# Infrastructure / 인프라 구현 상세

<a href="#english"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English"></a>
<a href="#korean"><img src="https://img.shields.io/badge/lang-한국어-red.svg" alt="Korean"></a>

<a id="english"></a>
## English

### 1. Overview
The infrastructure layer packages the AgentCore Runtime V2 container that BMA attaches to: an ARM64 `python:3.12-slim` image that runs the official BMA lifecycle server, the Codex `exec-server` binary, the read-only `aws_inventory` STDIO MCP server, and the four `skills/`. It exists so that every Seoul-region AWS read happens inside the Runtime role, never inside the Web Function.

### 2. Components
| Component | Path | Purpose |
|---|---|---|
| Runtime image | `runtime/Dockerfile` | `python:3.12-slim`, non-root user `app` (uid 1000), venv at `/opt/bma/venv`, exposes port 8080, entrypoint `mcp_bridge.py` |
| Runtime dependencies | `runtime/requirements.txt` | Pinned `boto3==1.43.118`, `mcp==1.30.0`, `opentelemetry-api==1.45.1` |
| Official lifecycle server | `runtime/lifecycle/server.py` | Unmodified `@aws/agentcore` 1.0.0 BMA lifecycle template (`/invocations`, starts `codex exec-server`) |
| HTTP to STDIO MCP bridge | `runtime/mcp_bridge.py` | Extends the lifecycle server; serves `application/vnd.seoul-aws.mcp+json` `tools/list` and `tools/call` only, 64 KiB body cap, 90 s tool timeout |
| Upstream provenance | `runtime/UPSTREAM.md`, `runtime/LICENSE-AGENTCORE` | Source URL, SHA-256 and Apache 2.0 license of the lifecycle file |
| Codex binary staging | `scripts/prepare_runtime.py` | Copies the official Codex 0.164.0 Linux ARM64 ELF into `runtime/bin/` after checking ELF machine 183 and `exec-server` flags |
| Container probe | `scripts/check_runtime.py` | Runs the built image with `--network none`, checks uid 1000, 4 skills, MCP STDIO and `/ping` |
| Build context filter | `.dockerignore` | Excludes `.env*`, `.venv`, `web`, `webapp`, `tests`, `docs`, `artifacts`, `infra`, `scripts` from the image |

### 3. Key Decisions
- Keep `runtime/lifecycle/server.py` byte-identical to the official template and add behavior only in `mcp_bridge.py` — upgrades and provenance checks stay a file diff against the published SHA-256 (`runtime/UPSTREAM.md`).
- Ship the MCP server and Skills inside the Runtime image instead of the Web Function — Seoul read permissions live only on the Runtime role, so the browser-facing function cannot query AWS resources (`docs/design.md`).
- Build for `linux/arm64` and validate the Codex ELF before `docker build` — BMA Runtime V2 expects the documented `exec-server` interface, and a wrong-architecture binary fails only at session time otherwise.
- Use the PUBLIC Runtime network mode with HTTPS egress and no cross-region VPC peering — the app runs in `us-east-1` while it reads `ap-northeast-2` control-plane APIs (`docs/design.md`).
- Bridge requests are limited to two JSON-RPC methods with a bounded body — the Converse path reaches the same STDIO MCP server through IAM-protected `InvokeAgentRuntime` without exposing a general command surface.

### 4. Code Pointers
- `runtime/Dockerfile:17` — fixed `APP_REGION`, `TARGET_REGION`, `AWS_REGION` and Codex paths baked into the image
- `runtime/Dockerfile:23` — entrypoint runs `/opt/bma/mcp_bridge.py` as user `app`
- `runtime/mcp_bridge.py:17` — media type, request size and tool timeout limits
- `runtime/mcp_bridge.py:64` — `McpProxy`, a real MCP `ClientSession` over a STDIO child process
- `scripts/prepare_runtime.py:15` — `prepare()` ELF, architecture and `exec-server` checks
- `scripts/check_runtime.py:16` — offline container probe with `--network none`

### 5. Cross-references
- Related modules: `runtime/`, `aws_inventory/`, `skills/`, `scripts/`
- Related ADRs: None yet (use /add-adr)
- Related runbooks: [deploy-production.md](../runbooks/deploy-production.md)
- Related docs: [architecture.md](../architecture.md), [iac.md](iac.md), [agent-llm.md](agent-llm.md), [design.md](../design.md), [aws-deployment.md](../aws-deployment.md)

<a id="korean"></a>
## 한국어

### 1. 개요
인프라 계층은 BMA가 연결하는 AgentCore Runtime V2 컨테이너를 패키징합니다. ARM64 `python:3.12-slim` 이미지에서 공식 BMA lifecycle 서버, Codex `exec-server` 바이너리, 읽기 전용 `aws_inventory` STDIO MCP 서버와 4개 `skills/`를 실행합니다. 서울 리전 AWS 조회가 Web Function이 아니라 항상 Runtime 역할 안에서만 일어나도록 하기 위해 존재합니다.

### 2. 구성요소
| 구성요소 | 경로 | 목적 |
|---|---|---|
| Runtime image | `runtime/Dockerfile` | `python:3.12-slim`, non-root 사용자 `app`(uid 1000), `/opt/bma/venv` venv, 포트 8080, 진입점 `mcp_bridge.py` |
| Runtime dependencies | `runtime/requirements.txt` | 고정 버전 `boto3==1.43.118`, `mcp==1.30.0`, `opentelemetry-api==1.45.1` |
| Official lifecycle server | `runtime/lifecycle/server.py` | 변경하지 않은 `@aws/agentcore` 1.0.0 BMA lifecycle 템플릿(`/invocations`, `codex exec-server` 시작) |
| HTTP to STDIO MCP bridge | `runtime/mcp_bridge.py` | lifecycle 서버를 확장해 `application/vnd.seoul-aws.mcp+json`의 `tools/list`, `tools/call`만 제공, 본문 64 KiB 제한, 도구 timeout 90초 |
| Upstream provenance | `runtime/UPSTREAM.md`, `runtime/LICENSE-AGENTCORE` | lifecycle 파일의 출처 URL, SHA-256, Apache 2.0 라이선스 |
| Codex binary staging | `scripts/prepare_runtime.py` | ELF machine 183과 `exec-server` 옵션을 확인한 뒤 공식 Codex 0.164.0 Linux ARM64 ELF를 `runtime/bin/`에 복사 |
| Container probe | `scripts/check_runtime.py` | 빌드된 이미지를 `--network none`으로 실행해 uid 1000, Skills 4개, MCP STDIO, `/ping` 확인 |
| Build context filter | `.dockerignore` | `.env*`, `.venv`, `web`, `webapp`, `tests`, `docs`, `artifacts`, `infra`, `scripts`를 이미지에서 제외 |

### 3. 주요 결정
- `runtime/lifecycle/server.py`는 공식 템플릿과 바이트 단위로 동일하게 두고 동작 추가는 `mcp_bridge.py`에서만 합니다 — 업그레이드와 출처 검증이 공개 SHA-256과의 파일 비교로 끝납니다(`runtime/UPSTREAM.md`).
- MCP 서버와 Skills를 Web Function이 아니라 Runtime 이미지에 넣습니다 — 서울 조회 권한이 Runtime 역할에만 있으므로 브라우저와 맞닿은 함수는 AWS 리소스를 조회할 수 없습니다(`docs/design.md`).
- `linux/arm64`로 빌드하고 `docker build` 전에 Codex ELF를 검증합니다 — BMA Runtime V2는 문서화된 `exec-server` 인터페이스를 기대하며, 아키텍처가 다른 바이너리는 세션 시점에야 실패합니다.
- Runtime은 PUBLIC 네트워크 모드와 HTTPS egress를 사용하고 리전 간 VPC Peering을 만들지 않습니다 — 앱은 `us-east-1`에서 실행되고 `ap-northeast-2` 제어 API를 조회합니다(`docs/design.md`).
- bridge 요청은 두 개의 JSON-RPC 메서드와 제한된 본문 크기로 한정합니다 — Converse 경로가 IAM으로 보호된 `InvokeAgentRuntime`을 통해 같은 STDIO MCP 서버를 사용하면서도 범용 명령 실행 경로를 노출하지 않습니다.

### 4. 코드 포인터
- `runtime/Dockerfile:17` — 이미지에 고정한 `APP_REGION`, `TARGET_REGION`, `AWS_REGION`과 Codex 경로
- `runtime/Dockerfile:23` — 사용자 `app`으로 `/opt/bma/mcp_bridge.py` 진입점 실행
- `runtime/mcp_bridge.py:17` — media type, 요청 크기, 도구 timeout 한도
- `runtime/mcp_bridge.py:64` — STDIO 자식 프로세스 위의 실제 MCP `ClientSession`인 `McpProxy`
- `scripts/prepare_runtime.py:15` — `prepare()`의 ELF, 아키텍처, `exec-server` 검사
- `scripts/check_runtime.py:16` — `--network none` 오프라인 컨테이너 검사

### 5. 상호 참조
- 관련 모듈: `runtime/`, `aws_inventory/`, `skills/`, `scripts/`
- 관련 ADR: 아직 없음 (/add-adr 사용)
- 관련 런북: [deploy-production.md](../runbooks/deploy-production.md)
- 관련 문서: [architecture.md](../architecture.md), [iac.md](iac.md), [agent-llm.md](agent-llm.md), [design.md](../design.md), [aws-deployment.md](../aws-deployment.md)
