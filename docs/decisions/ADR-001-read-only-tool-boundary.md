# ADR-001: Enforce the Read-Only Boundary with a Tool Registry and IAM Allow-List

<a href="#english"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English"></a>
<a href="#korean"><img src="https://img.shields.io/badge/lang-한국어-red.svg" alt="Korean"></a>

---

<a id="english"></a>

# English

## Status
Accepted (decided 2026-10-26 in [design.md](../design.md); recorded 2026-10-27)

## Context
The agent answers questions about real resources in one AWS account's `ap-northeast-2` region. The model
chooses which tools to call, and its instructions come from Skills and prompts that it may not follow
exactly. The system must never modify resources, never reach another account, and must keep credentials,
environment variables, endpoints and raw error text out of model input and stored evidence.

## Options Considered

### Option 1: Managed `ReadOnlyAccess` with a generic boto3 operation tool
- **Pros**: Any read API is available immediately; very little code per service.
- **Cons**: `ReadOnlyAccess` still exposes sensitive reads (for example Lambda environment variables, secrets metadata); the model controls operation names and parameters; output fields cannot be allow-listed per API; Skills and prompts become the only guard.

### Option 2: Explicit tool registry, strict input schemas and an exact IAM allow-list
- **Pros**: Each of the 24 tools has a pydantic schema (`extra="forbid"`, ID patterns), a bounded handler, a field allow-list in `normalize.py`, and only the IAM actions it needs on `RuntimeRole`; a per-call STS check pins the account; tests can assert the IAM scope.
- **Cons**: Every new capability needs schema, handler, normalization, IAM, tests and docs; the model cannot answer questions outside the registered tools.

## Decision
Adopt Option 2. The read-only boundary is the tool registry (`aws_inventory/schema.py`), input validation,
normalization and the `RuntimeRole` allow-list in `infra/template.yaml`. Skills only describe procedures.
No generic boto3 operation tool, shell or command MCP tool, or `ReadOnlyAccess` is added. Seoul read
permissions exist only on `RuntimeRole`; the Web Function, session and worker roles have none.

## Consequences

### Positive
- A prompt or Skill change cannot widen what the system reads; only reviewed code and IAM can.
- `tests/test_iam.py` and `tests/test_investigation_iam.py` verify the exact action sets.
- Results carry explicit `status`, `truncated` and `pagination_complete` instead of raw API output.

### Negative
- Adding a service is a multi-file change (see the Conventions section of the root `CLAUDE.md`).
- Unsupported questions return `unsupported_service` rather than a best-effort answer.

## References
- [design.md](../design.md) — Skills describe procedures; the boundary is the registry, validation and IAM
- [api-iam.md](../api-iam.md) — service API to IAM action mapping
- [data-and-scope.md](../data-and-scope.md) — excluded fields and data handling
- `aws_inventory/schema.py`, `aws_inventory/normalize.py`, `infra/template.yaml` (`RuntimeRole`)

---

<a id="korean"></a>

# 한국어

## 상태
승인됨([design.md](../design.md)에서 2026-10-26 결정, 2026-10-27 기록)

## 배경
에이전트는 한 AWS 계정의 `ap-northeast-2` 리전에 있는 실제 리소스에 대한 질문에 답합니다. 어떤 도구를
호출할지는 모델이 고르고, 그 지침은 모델이 정확히 따르지 않을 수도 있는 Skills와 프롬프트에서 옵니다.
시스템은 리소스를 절대 변경하지 않아야 하고, 다른 계정에 접근하지 않아야 하며, 자격증명·환경 변수·
접속 주소·원문 오류 메시지를 모델 입력과 저장 근거에서 제외해야 합니다.

## 검토한 옵션

### 옵션 1: 관리형 `ReadOnlyAccess`와 범용 boto3 operation 도구
- **장점**: 모든 읽기 API를 즉시 쓸 수 있고 서비스별 코드가 거의 필요 없습니다.
- **단점**: `ReadOnlyAccess`도 민감한 읽기(예: Lambda 환경 변수, 비밀 메타데이터)를 허용합니다. operation 이름과 파라미터를 모델이 정하고, API별 출력 필드 허용 목록을 둘 수 없으며, Skills와 프롬프트가 유일한 방어선이 됩니다.

### 옵션 2: 명시적 도구 레지스트리, 엄격한 입력 스키마, 정확한 IAM 허용 목록
- **장점**: 24개 도구마다 pydantic 스키마(`extra="forbid"`, ID 패턴), 범위가 제한된 핸들러, `normalize.py`의 필드 허용 목록, `RuntimeRole`의 필요한 IAM action만 둡니다. 호출마다 STS로 계정을 고정하고, 테스트로 IAM 범위를 검증할 수 있습니다.
- **단점**: 기능을 추가할 때마다 스키마, 핸들러, 정규화, IAM, 테스트, 문서를 함께 바꿔야 합니다. 등록된 도구 밖의 질문에는 답할 수 없습니다.

## 결정
옵션 2를 채택합니다. 읽기 전용 경계는 도구 레지스트리(`aws_inventory/schema.py`), 입력 검증, 정규화,
`infra/template.yaml`의 `RuntimeRole` 허용 목록입니다. Skills는 절차만 안내합니다. 범용 boto3 operation
도구, 셸·명령 실행 MCP 도구, `ReadOnlyAccess`는 추가하지 않습니다. 서울 조회 권한은 `RuntimeRole`에만
있고 Web Function, 세션, worker 역할에는 없습니다.

## 영향

### 긍정적
- 프롬프트나 Skill을 바꿔도 시스템이 읽는 범위는 넓어지지 않습니다. 검토된 코드와 IAM만 범위를 바꿀 수 있습니다.
- `tests/test_iam.py`와 `tests/test_investigation_iam.py`가 정확한 action 집합을 검증합니다.
- 결과에는 원문 API 응답 대신 명시적인 `status`, `truncated`, `pagination_complete`가 담깁니다.

### 부정적
- 서비스 하나를 추가하려면 여러 파일을 함께 바꿔야 합니다(root `CLAUDE.md`의 Conventions 참고).
- 지원하지 않는 질문에는 추정 답변 대신 `unsupported_service`를 반환합니다.

## 참고 자료
- [design.md](../design.md) — Skills는 절차를 안내하고 경계는 레지스트리, 검증, IAM이라는 설계
- [api-iam.md](../api-iam.md) — 서비스 API와 IAM action 대응표
- [data-and-scope.md](../data-and-scope.md) — 제외 필드와 데이터 처리
- `aws_inventory/schema.py`, `aws_inventory/normalize.py`, `infra/template.yaml`(`RuntimeRole`)
