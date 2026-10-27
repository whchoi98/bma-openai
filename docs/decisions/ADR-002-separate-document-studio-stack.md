# ADR-002: Run AI Document Studio as a Separate Stack with a Document-Only Runtime

<a href="#english"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English"></a>
<a href="#korean"><img src="https://img.shields.io/badge/lang-한국어-red.svg" alt="Korean"></a>

---

<a id="english"></a>

# English

## Status
Accepted (implemented and deployed 2026-10-27; plan in [2026-10-27-document-studio.md](../superpowers/plans/2026-10-27-document-studio.md))

## Context
AI Document Studio lets non-developers upload one spreadsheet or text file, or paste notes, and receive
charts, diagrams and editable PPTX/DOCX through BMA. Unlike the Operations Desk it must accept file
uploads, run Office and chart renderers, and store generated files, but it never needs to read AWS
resources. The existing desk deployment and its read-only boundary ([ADR-001](ADR-001-read-only-tool-boundary.md))
had to stay unchanged.

## Options Considered

### Option 1: Add document tools and routes to the existing desk stack
- **Pros**: One Web Function, Runtime and bucket; no new stacks to operate.
- **Cons**: The desk `RuntimeRole` and Runtime image would gain upload and Office capabilities next to Seoul read permissions; a document bug or prompt injection in an uploaded file would run where AWS read access exists; desk deployments and rollbacks would carry Studio changes.

### Option 2: Separate stacks, roles, bucket, Runtime image and job-bound MCP
- **Pros**: The document Runtime has no AWS resource-query permissions and reads only its fixed job's inputs (`--job-id UUID`); Web, worker, session and Runtime roles are separated; the desk stacks, roles and data bucket are untouched; Studio limits and 7-day retention are independent.
- **Cons**: Two more stacks (`bma-office-build`, `bma-office-studio`), a second Runtime image and a second deployment procedure; `web/bma.js`, `web/node_modules` and the Codex/lifecycle files are shared at build time.

## Decision
Adopt Option 2. Studio lives in `studio/` with its own CloudFormation, `RuntimeDockerfile`, Skills and
Web Function, deployed by `studio/scripts/deploy.py`. Its MCP exposes six document tools and no AWS
inventory, CLI, Python-execution or macro tools. Numbers come from code (`aggregate_chart()`), not the model.
The deployed model is `openai.gpt-6.1-sol`. In an early Luna trial the model linked a chart to the wrong
document reference, while Sol passed all three live styles. Model choice is a deployment parameter, not an
automatic fallback.

## Consequences

### Positive
- A Studio failure or malicious upload cannot reach Seoul read permissions or desk data.
- Studio can be deployed, updated or removed without touching the desk.
- `studio/tests/test_infra.py` checks the Studio IAM scope independently of `tests/test_iam.py`.

### Negative
- Template, `config.js` and `deploy.py` defaults still say `openai.gpt-6-luna`; the Sol deployment depends on `artifacts/studio/deployment.json` (see [the Studio runbook](../runbooks/deploy-document-studio.md)).
- Changes to `web/bma.js` or the shared Runtime files require rebuilding and testing both apps.
- The shared access key makes Studio a trusted-group demo, not a per-user tenant service.

## References
- [document-studio.md](../document-studio.md) — usage, limits, data flow and live verification
- [studio/README.md](../../studio/README.md) — product requirements, interfaces and API
- [architecture.md](../architecture.md#ai-document-studio) — components and resources

---

<a id="korean"></a>

# 한국어

## 상태
채택(2026-10-27 구현·배포, 계획은 [2026-10-27-document-studio.md](../superpowers/plans/2026-10-27-document-studio.md))

## 배경
AI Document Studio는 비개발자가 스프레드시트나 텍스트 파일 하나를 올리거나 메모를 붙여 넣으면 BMA를 통해
차트, 다이어그램, 편집 가능한 PPTX/DOCX를 만들어 줍니다. 운영 데스크와 달리 파일 업로드를 받고 Office·차트
렌더러를 실행하며 생성 파일을 저장해야 하지만, AWS 리소스를 조회할 필요는 없습니다. 기존 데스크 배포와 읽기 전용
경계([ADR-001](ADR-001-read-only-tool-boundary.md))는 바뀌지 않아야 했습니다.

## 검토한 옵션

### 옵션 1: 기존 데스크 스택에 문서 도구와 경로 추가
- **장점**: Web Function, Runtime, 버킷이 하나이며 운영할 스택이 늘지 않습니다.
- **단점**: 데스크 `RuntimeRole`과 Runtime 이미지에 서울 조회 권한과 함께 업로드·Office 기능이 생깁니다. 업로드 파일의 문서 버그나 프롬프트 주입이 AWS 조회 권한이 있는 곳에서 실행되고, 데스크 배포와 롤백에 Studio 변경이 섞입니다.

### 옵션 2: 별도 스택, 역할, 버킷, Runtime 이미지, 작업 고정 MCP
- **장점**: 문서 Runtime에는 AWS 리소스 조회 권한이 없고 고정된 작업의 입력만 읽습니다(`--job-id UUID`). Web, worker, 세션, Runtime 역할이 분리되고 데스크 스택·역할·데이터 버킷은 그대로이며, Studio 한도와 7일 보관을 따로 관리합니다.
- **단점**: 스택 두 개(`bma-office-build`, `bma-office-studio`), 두 번째 Runtime 이미지, 두 번째 배포 절차가 생깁니다. `web/bma.js`, `web/node_modules`, Codex/lifecycle 파일은 빌드할 때 공유합니다.

## 결정
옵션 2를 채택합니다. Studio는 자체 CloudFormation, `RuntimeDockerfile`, Skills, Web Function과 함께 `studio/`에
두고 `studio/scripts/deploy.py`로 배포합니다. MCP는 문서 도구 6개만 제공하며 AWS 인벤토리, CLI, Python 실행,
매크로 도구는 없습니다. 숫자는 모델이 아니라 코드(`aggregate_chart()`)가 계산합니다.
배포 모델은 `openai.gpt-6.1-sol`입니다. 초기 Luna 시험에서 모델이 차트를 잘못된 문서 참조에 연결했고,
Sol은 세 가지 실제 스타일 검증을 모두 통과했습니다. 모델 선택은 배포 파라미터이며 자동 대체 경로가 아닙니다.

## 영향

### 긍정적
- Studio 장애나 악의적인 업로드가 서울 조회 권한이나 데스크 데이터에 닿지 않습니다.
- 데스크를 건드리지 않고 Studio를 배포, 갱신, 제거할 수 있습니다.
- `studio/tests/test_infra.py`가 `tests/test_iam.py`와 별도로 Studio IAM 범위를 검사합니다.

### 부정적
- 템플릿, `config.js`, `deploy.py`의 기본값은 아직 `openai.gpt-6-luna`이며, Sol 배포는 `artifacts/studio/deployment.json`에 의존합니다([Studio 런북](../runbooks/deploy-document-studio.md) 참고).
- `web/bma.js`나 공유 Runtime 파일을 바꾸면 두 앱을 모두 다시 빌드하고 테스트해야 합니다.
- 공유 이용 키를 쓰므로 Studio는 신뢰된 그룹용 데모이며 사용자별 테넌트 서비스가 아닙니다.

## 참고 자료
- [document-studio.md](../document-studio.md) — 사용법, 한도, 데이터 흐름, 실제 검증
- [studio/README.md](../../studio/README.md) — 제품 요구 사항, 인터페이스, API
- [architecture.md](../architecture.md#ai-document-studio-1) — 구성 요소와 리소스
