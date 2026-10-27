# Infrastructure as Code / IaC 구현 상세

<a href="#english"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English"></a>
<a href="#korean"><img src="https://img.shields.io/badge/lang-한국어-red.svg" alt="Korean"></a>

<a id="english"></a>
## English

### 1. Overview
Two CloudFormation templates define every AWS resource in `us-east-1`: `infra/bootstrap.yaml` creates the build stores (ECR repository and versioned code bucket), and `infra/template.yaml` creates the four IAM roles, the AgentCore Runtime V2, the Lambda Web Function with its revision and endpoint, the investigation worker Lambda, the app state bucket and log groups. The IaC layer exists to keep role separation and region scoping reviewable as code and enforced by tests.

### 2. Components
| Component | Path | Purpose |
|---|---|---|
| Build stack | `infra/bootstrap.yaml` | `RuntimeRepository` (ECR, `IMMUTABLE` tags, scan on push), `CodeBucket` (versioned, SSE, public access blocked), TLS-only bucket policy, `VirginiaOnly` rule |
| App stack | `infra/template.yaml` | Parameters for model, backend, code location, access token (`NoEcho`) and limits; `DeployInAppRegion` rule |
| IAM roles | `infra/template.yaml` | `RuntimeRole` (Seoul reads), `SessionRole` (model and Runtime only), `WebRole` (BMA calls, app state), `WorkerRole` (BMA session API, limited state) |
| Runtime | `infra/template.yaml` | `AWS::BedrockAgentCore::Runtime`, `PlatformVersion: V2`, `NetworkMode: PUBLIC`, `ProtocolConfiguration: HTTP`, 900 s idle timeout |
| Web Function | `infra/template.yaml` | `AWS::Lambda::WebFunction`, `WebFunctionRevision` (`nodejs24.x`, S3 object with `VersionId`, 600 s timeout), `WebFunctionEndpoint` (`WebEndpointAuthType`, default and deployed `IamAuth`; 2 environments, 100 rps) |
| CloudFront front door | `infra/template.yaml`, `studio/infra/template.yaml` | `AWS::CloudFront::Distribution` (`PriceClass_All`, inline `ForwardedValues`: public `/` and `/static/*`, TTL 0 elsewhere) and `AWS::CloudFront::OriginAccessControl` (`lambda`, `sigv4`, `always-amz-auth`); the endpoint resource policy is applied by `scripts/deploy_cloudfront.py`, outside CloudFormation |
| Investigation worker | `infra/template.yaml` | `AWS::Lambda::Function` (`nodejs24.x`, 512 MB, 360 s, reserved concurrency 2) and `EventInvokeConfig` (1 retry, 600 s max age) |
| App state and logs | `infra/template.yaml` | `AppState` bucket (Retain, versioned, 7-day expiry on `runs/`, `history/`, `investigations/`), TLS-only policy, `WebLogs` and `WorkerLogs` (7-day retention) |
| Parameter file writer | `scripts/deployment_parameters.py` | Writes `artifacts/deploy-parameters.json` with file mode 0600 without printing secrets |
| Policy tests | `tests/test_iam.py`, `tests/test_investigation_iam.py` | Assert Seoul-only reads, no mutations, single-role `iam:PassRole`, designated model and Runtime |

### 3. Key Decisions
- Split build stores (`bma-seoul-build`) from the app stack (`bma-seoul-inventory`) — the image digest and code `VersionId` must exist before the Runtime and Web Revision can reference them immutably.
- Condition every Runtime read action on `aws:RequestedRegion = TargetRegion` — the Runtime role can only reach `ap-northeast-2` even though the stack runs in `us-east-1` (`docs/api-iam.md`).
- Grant no managed `ReadOnlyAccess` and enumerate only implemented API actions — `tests/test_iam.py` fails when a mutation or an unimplemented operation appears in the Runtime policy.
- Assert the deploy region with CloudFormation `Rules` in both templates — a stack created in the wrong region fails before any resource is created.
- Expire app state after 7 days and retain buckets and log groups on stack deletion — reports and investigation snapshots stay bounded in cost while evidence survives an accidental stack delete (`docs/data-and-scope.md`).

### 4. Code Pointers
- `infra/bootstrap.yaml:22` — `RuntimeRepository` with immutable tags and scan on push
- `infra/template.yaml:73` — `DeployInAppRegion` rule pinning the stack to `us-east-1`
- `infra/template.yaml:135` — `RuntimeRole` with `aws:RequestedRegion` conditions on Seoul reads
- `infra/template.yaml:281` — `Runtime` V2 resource definition
- `infra/template.yaml:310` — `SessionRole` limited to `bedrock-mantle:CreateInference` for one model plus Runtime invoke/stop
- `infra/template.yaml:562` — `WebRevision` environment variables and code reference
- `scripts/deployment_parameters.py:66` — 0600 parameter file creation

### 5. Cross-references
- Related modules: `infra/`, `scripts/`, `tests/`
- Related ADRs: None yet (use /add-adr)
- Related runbooks: [deploy-production.md](../runbooks/deploy-production.md)
- Related docs: [architecture.md](../architecture.md), [security.md](security.md), [infrastructure.md](infrastructure.md), [api-iam.md](../api-iam.md), [aws-deployment.md](../aws-deployment.md)

<a id="korean"></a>
## 한국어

### 1. 개요
두 개의 CloudFormation 템플릿이 `us-east-1`의 모든 AWS 리소스를 정의합니다. `infra/bootstrap.yaml`은 빌드 저장소(ECR 저장소와 버전 관리되는 코드 버킷)를 만들고, `infra/template.yaml`은 IAM 역할 4개, AgentCore Runtime V2, revision과 endpoint를 포함한 Lambda Web Function, 운영 조사 worker Lambda, 앱 상태 버킷과 로그 그룹을 만듭니다. IaC 계층은 역할 분리와 리전 범위를 코드로 검토하고 테스트로 강제하기 위해 존재합니다.

### 2. 구성요소
| 구성요소 | 경로 | 목적 |
|---|---|---|
| Build stack | `infra/bootstrap.yaml` | `RuntimeRepository`(ECR, `IMMUTABLE` 태그, push 시 스캔), `CodeBucket`(버전 관리, SSE, 퍼블릭 접근 차단), TLS 전용 버킷 정책, `VirginiaOnly` 규칙 |
| App stack | `infra/template.yaml` | 모델, 백엔드, 코드 위치, 접속 키(`NoEcho`), 한도 파라미터와 `DeployInAppRegion` 규칙 |
| IAM roles | `infra/template.yaml` | `RuntimeRole`(서울 조회), `SessionRole`(모델과 Runtime만), `WebRole`(BMA 호출, 앱 상태), `WorkerRole`(BMA 세션 API, 제한된 상태) |
| Runtime | `infra/template.yaml` | `AWS::BedrockAgentCore::Runtime`, `PlatformVersion: V2`, `NetworkMode: PUBLIC`, `ProtocolConfiguration: HTTP`, 유휴 timeout 900초 |
| Web Function | `infra/template.yaml` | `AWS::Lambda::WebFunction`, `WebFunctionRevision`(`nodejs24.x`, `VersionId`를 지정한 S3 객체, timeout 600초), `WebFunctionEndpoint`(`WebEndpointAuthType`, 기본값과 현재 배포 모두 `IamAuth`, 환경 2개, 100 rps) |
| CloudFront front door | `infra/template.yaml`, `studio/infra/template.yaml` | `AWS::CloudFront::Distribution`(`PriceClass_All`, 인라인 `ForwardedValues`: 공개 `/`와 `/static/*`, 나머지 TTL 0)과 `AWS::CloudFront::OriginAccessControl`(`lambda`, `sigv4`, `always-amz-auth`), 엔드포인트 리소스 정책은 CloudFormation 밖에서 `scripts/deploy_cloudfront.py`가 적용 |
| Investigation worker | `infra/template.yaml` | `AWS::Lambda::Function`(`nodejs24.x`, 512 MB, 360초, 예약 동시성 2)과 `EventInvokeConfig`(재시도 1회, 최대 600초) |
| App state and logs | `infra/template.yaml` | `AppState` 버킷(Retain, 버전 관리, `runs/`, `history/`, `investigations/` 7일 만료), TLS 전용 정책, `WebLogs`와 `WorkerLogs`(7일 보존) |
| Parameter file writer | `scripts/deployment_parameters.py` | 비밀 값을 출력하지 않고 파일 모드 0600으로 `artifacts/deploy-parameters.json` 작성 |
| Policy tests | `tests/test_iam.py`, `tests/test_investigation_iam.py` | 서울 전용 조회, 변경 작업 없음, 단일 역할 `iam:PassRole`, 지정 모델과 Runtime을 검증 |

### 3. 주요 결정
- 빌드 저장소(`bma-seoul-build`)와 앱 스택(`bma-seoul-inventory`)을 분리합니다 — Runtime과 Web Revision이 불변 참조로 쓰려면 이미지 digest와 코드 `VersionId`가 먼저 있어야 합니다.
- Runtime의 모든 조회 작업에 `aws:RequestedRegion = TargetRegion` 조건을 둡니다 — 스택은 `us-east-1`에서 실행되지만 Runtime 역할은 `ap-northeast-2`만 조회할 수 있습니다(`docs/api-iam.md`).
- 관리형 `ReadOnlyAccess`를 부여하지 않고 구현한 API 작업만 나열합니다 — Runtime 정책에 변경 작업이나 구현하지 않은 작업이 들어가면 `tests/test_iam.py`가 실패합니다.
- 두 템플릿 모두 CloudFormation `Rules`로 배포 리전을 검증합니다 — 잘못된 리전에서 만든 스택은 리소스 생성 전에 실패합니다.
- 앱 상태는 7일 후 만료하고 버킷과 로그 그룹은 스택 삭제 시 보존합니다 — 보고서와 조사 스냅샷의 비용을 제한하면서 실수로 스택을 삭제해도 근거가 남습니다(`docs/data-and-scope.md`).

### 4. 코드 포인터
- `infra/bootstrap.yaml:22` — 불변 태그와 push 시 스캔을 설정한 `RuntimeRepository`
- `infra/template.yaml:73` — 스택을 `us-east-1`로 고정하는 `DeployInAppRegion` 규칙
- `infra/template.yaml:135` — 서울 조회에 `aws:RequestedRegion` 조건을 둔 `RuntimeRole`
- `infra/template.yaml:281` — `Runtime` V2 리소스 정의
- `infra/template.yaml:310` — 단일 모델의 `bedrock-mantle:CreateInference`와 Runtime invoke/stop만 허용하는 `SessionRole`
- `infra/template.yaml:562` — `WebRevision` 환경 변수와 코드 참조
- `scripts/deployment_parameters.py:66` — 0600 파라미터 파일 생성

### 5. 상호 참조
- 관련 모듈: `infra/`, `scripts/`, `tests/`
- 관련 ADR: 아직 없음 (/add-adr 사용)
- 관련 런북: [deploy-production.md](../runbooks/deploy-production.md)
- 관련 문서: [architecture.md](../architecture.md), [security.md](security.md), [infrastructure.md](infrastructure.md), [api-iam.md](../api-iam.md), [aws-deployment.md](../aws-deployment.md)
