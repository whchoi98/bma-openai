# Security / 보안 구현 상세

<a href="#english"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English"></a>
<a href="#korean"><img src="https://img.shields.io/badge/lang-한국어-red.svg" alt="Korean"></a>

<a id="english"></a>
## English

### 1. Overview
The security layer keeps the demo read-only, single-account and region-bounded. Every tool call re-verifies the Runtime account with STS against `EXPECTED_ACCOUNT_ID` before any resource API, AWS clients are pinned to fixed regions, results pass through field allow-lists, and IAM splits permissions across four roles so that only the Runtime role can read Seoul resources. The browser-facing API is protected by a shared bearer key compared in constant time.

### 2. Components
| Component | Path | Purpose |
|---|---|---|
| Settings guard | `aws_inventory/config.py` | Rejects any region pair other than `us-east-1` / `ap-northeast-2`, non-12-digit accounts, and sample/live account mix-ups; `SDK_SERVICES` allow-list |
| Account and region enforcement | `aws_inventory/engine.py` | `client()` pins STS to `APP_REGION` and resource clients to `TARGET_REGION`; `_verify_account()` stops with `account_mismatch` before resource calls |
| Field allow-lists | `aws_inventory/normalize.py` | Per-service normalizers that drop Lambda environment variables, DB endpoints and usernames, EC2 tags and private IPs, raw error text |
| API authentication | `web/server.js`, `webapp/main.py` | `Authorization: Bearer <APP_ACCESS_TOKEN>` on `/api/*` with `timingSafeEqual` / `hmac.compare_digest`; 16 KiB request body cap |
| Response headers | `web/server.js` | `no-store` (public `Cache-Control` only on anonymous static files), `nosniff`, `no-referrer`, CSP `default-src 'self'` with `frame-ancestors 'none'` |
| Origin access | `infra/template.yaml`, `scripts/deploy_cloudfront.py` | Endpoint `IamAuth`; only the app's own CloudFront distribution (OAC `sigv4`, exact `aws:SourceArn`) may invoke it; direct origin requests return 403 even with a valid key |
| IAM role separation | `infra/template.yaml` | Runtime role: Seoul reads only; Session role: one model plus designated Runtime; Web role: BMA calls, PassRole to one role, app state; Worker role: BMA session API and limited state |
| Policy tests | `tests/test_iam.py`, `tests/test_investigation_iam.py` | Fail on mutations, unimplemented operations, wider PassRole or global inference in the BMA path |
| Secret handling | `scripts/deployment_parameters.py`, `.gitignore`, `.env.example` | 0600 parameter file, `NoEcho` token parameter, `artifacts/` and `.env` git-ignored, placeholders only in `.env.example` |
| Commit secret scan | `.claude/hooks/secret-scan.sh` | Claude Code PreToolUse hook that blocks `git commit` when staged files match secret patterns |

### 3. Key Decisions
- Re-verify the Runtime account on every tool call instead of trusting deployment-time configuration — credentials that resolve to another account cause `account_mismatch` with zero resource API calls (`docs/design.md`).
- Do not attach managed `ReadOnlyAccess` and do not expose an arbitrary command or generic boto3 operation tool — the read-only boundary is the explicit tool registry, input validation and IAM allow-list, not the Skills text.
- Give the Web Function no Seoul read permission — a compromised web process can call BMA and the app bucket but cannot enumerate AWS resources directly.
- Use one shared access key for trusted demo users and keep it in browser memory only — this is a documented trade-off; per-user identity and tenant isolation are out of scope (`README.md`).
- Never store or emit reasoning, analysis messages or raw `command_execution` output — only public answer deltas and normalized `seoul_aws` tool results reach the browser and S3 (`docs/data-and-scope.md`).

### 4. Code Pointers
- `aws_inventory/config.py:30` — fixed region pair check
- `aws_inventory/engine.py:118` — region-pinned client factory with `SDK_SERVICES` allow-list
- `aws_inventory/engine.py:186` — `_verify_account()` STS comparison
- `aws_inventory/normalize.py:92` — `lambda_function()` normalizer that excludes environment and role details
- `web/server.js:37` — constant-time token comparison
- `web/server.js:90` — bearer check on `/api/*`
- `infra/template.yaml:42` — `AppAccessToken` parameter with `NoEcho` and 32-character minimum

### 5. Cross-references
- Related modules: `aws_inventory/`, `web/`, `webapp/`, `infra/`, `.claude/hooks/`
- Related ADRs: None yet (use /add-adr)
- Related runbooks: [deploy-production.md](../runbooks/deploy-production.md)
- Related docs: [architecture.md](../architecture.md), [iac.md](iac.md), [agent-llm.md](agent-llm.md), [api-iam.md](../api-iam.md), [data-and-scope.md](../data-and-scope.md), [verification.md](../verification.md)

<a id="korean"></a>
## 한국어

### 1. 개요
보안 계층은 데모를 읽기 전용, 단일 계정, 지정 리전 범위로 유지합니다. 모든 도구 호출은 리소스 API를 부르기 전에 STS로 Runtime 계정을 `EXPECTED_ACCOUNT_ID`와 다시 비교하고, AWS 클라이언트는 고정 리전에 묶이며, 결과는 필드 허용 목록을 거칩니다. IAM은 권한을 네 개 역할로 나누어 Runtime 역할만 서울 리소스를 조회할 수 있습니다. 브라우저용 API는 상수 시간 비교를 하는 공유 bearer 키로 보호합니다.

### 2. 구성요소
| 구성요소 | 경로 | 목적 |
|---|---|---|
| Settings guard | `aws_inventory/config.py` | `us-east-1` / `ap-northeast-2` 외의 리전 조합, 12자리가 아닌 계정, 샘플/실제 계정 혼용을 거부하고 `SDK_SERVICES` 허용 목록을 정의 |
| Account and region enforcement | `aws_inventory/engine.py` | `client()`가 STS는 `APP_REGION`, 리소스 클라이언트는 `TARGET_REGION`으로 고정하고 `_verify_account()`가 리소스 호출 전에 `account_mismatch`로 중단 |
| Field allow-lists | `aws_inventory/normalize.py` | Lambda 환경 변수, DB 접속 주소와 사용자명, EC2 태그와 사설 IP, 원문 오류를 제거하는 서비스별 정규화 함수 |
| API authentication | `web/server.js`, `webapp/main.py` | `/api/*`에 `Authorization: Bearer <APP_ACCESS_TOKEN>`을 요구하고 `timingSafeEqual` / `hmac.compare_digest`로 비교, 요청 본문 16 KiB 제한 |
| Response headers | `web/server.js` | `no-store`(익명 정적 파일만 공개 `Cache-Control`), `nosniff`, `no-referrer`, `frame-ancestors 'none'`을 포함한 CSP `default-src 'self'` |
| Origin access | `infra/template.yaml`, `scripts/deploy_cloudfront.py` | 엔드포인트 `IamAuth`, 해당 앱의 CloudFront 배포(OAC `sigv4`, 정확한 `aws:SourceArn`)만 호출 가능, 올바른 키가 있어도 오리진 직접 요청은 403 |
| IAM role separation | `infra/template.yaml` | Runtime 역할: 서울 조회만, Session 역할: 단일 모델과 지정 Runtime, Web 역할: BMA 호출·단일 역할 PassRole·앱 상태, Worker 역할: BMA 세션 API와 제한된 상태 |
| Policy tests | `tests/test_iam.py`, `tests/test_investigation_iam.py` | 변경 작업, 구현하지 않은 작업, 더 넓은 PassRole, BMA 경로의 글로벌 추론 권한이 생기면 실패 |
| Secret handling | `scripts/deployment_parameters.py`, `.gitignore`, `.env.example` | 0600 파라미터 파일, `NoEcho` 토큰 파라미터, `artifacts/`와 `.env`의 git 제외, `.env.example`에는 빈 값만 |
| Commit secret scan | `.claude/hooks/secret-scan.sh` | staged 파일이 비밀 패턴과 일치하면 `git commit`을 막는 Claude Code PreToolUse hook |

### 3. 주요 결정
- 배포 시점 설정을 믿지 않고 도구 호출마다 Runtime 계정을 다시 확인합니다 — 다른 계정으로 해석되는 자격증명은 리소스 API를 한 번도 호출하지 않고 `account_mismatch`가 됩니다(`docs/design.md`).
- 관리형 `ReadOnlyAccess`를 붙이지 않고 임의 명령이나 범용 boto3 operation 도구를 노출하지 않습니다 — 읽기 전용 경계는 Skills 문구가 아니라 명시적 도구 레지스트리, 입력 검증, IAM 허용 목록입니다.
- Web Function에는 서울 조회 권한을 주지 않습니다 — 웹 프로세스가 침해되어도 BMA와 앱 버킷만 호출할 수 있고 AWS 리소스를 직접 나열할 수 없습니다.
- 신뢰된 데모 사용자를 위해 공유 접속 키 하나를 쓰고 브라우저 메모리에만 둡니다 — 문서화한 트레이드오프이며 사용자별 인증과 테넌트 격리는 범위 밖입니다(`README.md`).
- reasoning, analysis 메시지, `command_execution` 원문은 저장하거나 내보내지 않습니다 — 공개 답변 delta와 정규화된 `seoul_aws` 도구 결과만 브라우저와 S3에 전달됩니다(`docs/data-and-scope.md`).

### 4. 코드 포인터
- `aws_inventory/config.py:30` — 고정 리전 조합 검사
- `aws_inventory/engine.py:118` — `SDK_SERVICES` 허용 목록을 적용한 리전 고정 클라이언트 생성
- `aws_inventory/engine.py:186` — STS를 비교하는 `_verify_account()`
- `aws_inventory/normalize.py:92` — 환경 변수와 역할 정보를 제외하는 `lambda_function()` 정규화 함수
- `web/server.js:37` — 상수 시간 토큰 비교
- `web/server.js:90` — `/api/*` bearer 검사
- `infra/template.yaml:42` — `NoEcho`와 최소 32자를 적용한 `AppAccessToken` 파라미터

### 5. 상호 참조
- 관련 모듈: `aws_inventory/`, `web/`, `webapp/`, `infra/`, `.claude/hooks/`
- 관련 ADR: 아직 없음 (/add-adr 사용)
- 관련 런북: [deploy-production.md](../runbooks/deploy-production.md)
- 관련 문서: [architecture.md](../architecture.md), [iac.md](iac.md), [agent-llm.md](agent-llm.md), [api-iam.md](../api-iam.md), [data-and-scope.md](../data-and-scope.md), [verification.md](../verification.md)
