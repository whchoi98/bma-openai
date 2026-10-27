# awsops_v2 연동 검토

후속 구현에서는 사용자의 정정에 따라 원본 `/home/ec2-user/my-project/awsops`에서 추출했다.
구현과 실제 검증은 [원본 추출 기록](awsops-extraction.md)을 참고한다.
아래 내용은 awsops_v2를 읽기 전용으로 검토했던 당시의 기록이다.

검토일: 2026-10-27 UTC  
대상: `/home/ec2-user/my-project/awsops_v2`  
기준 커밋: `603fd66b56333a853d139635428b690a2e0cb9e4`  
작업 트리: 변경 없음

코드를 읽고 현재 운영 데스크와 연결할 수 있는 부분을 확인했다. awsops_v2의 실행 환경에 접속하거나
새 연동을 배포한 결과는 아니다. 해당 저장소는 수정하지 않았다.

**우선 적용할 후보는 VPC, EBS, ECR 조회와 관계도, 기존 조회 결과를 이용한 DOCX/PPTX 내보내기다.**
기존 SQL을 범용 도구로 연결하기보다, 조회 항목과 화면 구성을 참고해 현재의 고정 boto3 도구로
옮기는 방식이 계정 검증, 최소 권한, 조회 근거 형식을 유지하기 쉽다.

## 확인한 구조

awsops_v2는 Next.js 화면, Fastify API, Steampipe, Aurora로 나뉜다.
서비스별 정적 SQL은 `packages/core/src`, API는 `apps/api/src/routes`에 있다.
API 등록은 [app.ts](../../awsops_v2/apps/api/src/app.ts), 의존성 구성은
[deps.ts](../../awsops_v2/apps/api/src/deps.ts)에서 확인했다.

현재 운영 데스크와의 주요 차이는 다음과 같다.

| 항목 | 현재 운영 데스크 | awsops_v2 코드 |
| --- | --- | --- |
| 실행과 모델 호출 | us-west-2, Luna, ConverseStream | Bedrock/AgentCore 클라이언트의 기본값이 ap-northeast-2, Sonnet/Opus 설정 |
| AWS 조회 | Runtime의 고정 boto3 MCP 도구 | Steampipe의 정적 SQL 또는 모델 생성 SQL, 별도 AgentCore 호출 |
| 계정 선택 | STS와 EXPECTED_ACCOUNT_ID로 고정 | API accountId와 Steampipe 연결 선택, 여러 계정 설정 |
| 저장 | us-west-2의 S3 조회 기록 | Aurora의 스냅샷/보고서 이력과 S3 파일 |
| 인증 | 앱 접속 키 | Cognito ID 토큰 쿠키 검증 |
| 결과 근거 | API, 시각, 계정, 리전, 페이지 상태 | 경로별로 rows/error 또는 저장 스냅샷 반환 |

Steampipe의 현재 AWS 연결 설정은 서울 리전이다. 다만 여러 계정 연결이 있으며,
accountId를 생략하면 명시적인 단일 계정 search_path 설정을 하지 않는다.
[aws.spc](../../awsops_v2/services/steampipe/config/aws.spc),
[search-path.ts](../../awsops_v2/packages/core/src/search-path.ts).

## 연동 후보

| 후보 | 실제 확인한 구현 | 권장 적용 방식 | 추가 조건 |
| --- | --- | --- | --- |
| **VPC와 네트워크 관계도** | VPC, 서브넷, 보안 그룹, 라우팅 테이블, NAT/IGW/TGW 조회 API와 React Flow 그래프 생성 함수 | `get_vpc_topology(vpc_id)` 등 고정 MCP 도구와 결과 그래프 추가 | 조회된 ID 사이의 구성 관계만 그린다. 실제 통신 가능 여부로 해석하지 않는다. |
| **EBS, ECR** | 볼륨/연결/암호화/스냅샷, 저장소/태그 변경 정책/스캔 설정 조회 SQL과 API | `list_ebs_volumes`, `list_ecr_repositories`처럼 서비스별 조회 도구 추가 | 리소스 수와 페이지 상한을 적용한다. 스캔 시작, 삭제, 볼륨 변경은 제외한다. |
| **S3, DynamoDB** | 버킷 설정, 공개 접근, 버전 관리, 테이블 상태/용량/암호화 설정 조회 | 제어 API의 구성 정보만 정규화해 추가 | S3 객체 내용, DynamoDB 항목 Query/Scan은 별도 범위다. 전역 목록과 서울 리전 필터도 구분한다. |
| **ElastiCache, OpenSearch, MSK** | 클러스터/복제 그룹/도메인과 상세 조회 경로 | 서비스별 인벤토리와 구성 상태 점검을 단계적으로 추가 | 캐시 명령, 검색 문서, Kafka 메시지 조회는 포함하지 않는다. |
| **보안 구성 점검** | 공개 S3, 공개 인바운드 SG, 암호화되지 않은 EBS, RDS 공개 접근 등의 SQL과 10개 구성 점검 규칙 | 관측 사실 중심의 `aws-security-posture` 절차와 고정 도구 | 권한 부족/누락을 통과로 바꾸지 않는다. 이 규칙만으로 전체 보안이나 CIS 준수를 판정하지 않는다. |
| **인벤토리 이력** | Aurora 스냅샷 저장, 최신 개수, 기간별 추세 API | 현재 S3 조회 기록의 계정/리전/범위별 이력과 비교 화면부터 추가 | 잘린 목록의 수를 전체 개수로 비교하지 않는다. 계정 필터와 원본 관측 시각을 보강해야 한다. |
| **DOCX/PPTX 내보내기** | 문서/슬라이드 생성 함수, S3 저장과 다운로드 코드 | 현재 Markdown/HTML 보고서의 정규화된 근거를 포맷 생성기에 전달 | 계정 마스킹, 한영 문구, 나눔스퀘어, 출력 크기 상한을 적용한다. 모델 재호출 없이 포맷 변환부터 재사용할 수 있다. |
| **비용, 감사 이벤트, 추가 지표** | Cost Explorer 계열 Steampipe 테이블, CloudTrail 이벤트, CloudWatch 지표 선택 API | 별도 기능으로 범위를 합의한 뒤 제한된 도구 추가 | 기간, 최대 호출/행 수, 과금 항목, 개인정보 필터가 필요하다. 비용과 로그 검색은 현재 데모의 제외 범위다. |
| **EKS/Kubernetes** | EKS 제어면 정보와 Kubernetes 객체 조회를 분리한 경로 | EKS 제어 API 인벤토리를 먼저 검토하고, Pod/노드 조회는 후속 단계로 분리 | Kubernetes API 접근은 네트워크, kubeconfig, 인증과 RBAC 구성이 필요하다. |

주요 소스:

- VPC: [routes/vpc.ts](../../awsops_v2/apps/api/src/routes/vpc.ts),
  [buildTopologyGraph.ts](../../awsops_v2/apps/web/src/lib/topology/buildTopologyGraph.ts)
- 추가 리소스: [ebs.ts](../../awsops_v2/packages/core/src/ebs.ts),
  [ecr.ts](../../awsops_v2/packages/core/src/ecr.ts),
  [s3.ts](../../awsops_v2/packages/core/src/s3.ts),
  [dynamodb.ts](../../awsops_v2/packages/core/src/dynamodb.ts)
- 보안: [security.ts](../../awsops_v2/packages/core/src/security.ts),
  [compliance.ts](../../awsops_v2/packages/core/src/compliance.ts),
  [routes/compliance.ts](../../awsops_v2/apps/api/src/routes/compliance.ts)
- 이력: [inventory-ingest.ts](../../awsops_v2/apps/api/src/lib/inventory-ingest.ts),
  [repos/inventory.ts](../../awsops_v2/packages/db/src/repos/inventory.ts)
- 내보내기: [report-docx.ts](../../awsops_v2/apps/api/src/lib/report-docx.ts),
  [report-pptx.ts](../../awsops_v2/apps/api/src/lib/report-pptx.ts),
  [report-store.ts](../../awsops_v2/apps/api/src/lib/report-store.ts)
- 확장 기능: [routes/k8s.ts](../../awsops_v2/apps/api/src/routes/k8s.ts),
  [routes/monitoring.ts](../../awsops_v2/apps/api/src/routes/monitoring.ts),
  [cloudtrail.ts](../../awsops_v2/packages/core/src/cloudtrail.ts),
  [cost.ts](../../awsops_v2/packages/core/src/cost.ts)

## 이름이나 화면만 보고 연결 가능하다고 판단하면 안 되는 부분

| 확인 사항 | 코드 근거 | 현재 앱에 적용할 기준 |
| --- | --- | --- |
| **외부 데이터 소스 조회는 미구현** | `routes/datasources.ts:32`의 explore는 외부 호출 없이 503과 `degraded: true`를 반환 | Prometheus, Loki, Tempo, ClickHouse는 등록 화면이 있어도 실제 연동 완료로 표시하지 않는다. |
| **일부 AI 기능은 일반 모델 답변으로 대체됨** | `routes/ai.ts:102`, `:177`의 fallback. `core/ai.ts`의 auto-collect, datasource, code 분류는 이름만으로 실행을 보장하지 않음 | 유휴 자원 탐색, 자동 rightsizing, 분산 추적, 사고 분석을 검증된 실조회 도구로 취급하지 않는다. |
| **Gateway 이름과 도구 목록은 구현 증거가 아님** | `core/ai.ts`의 ROUTE_REGISTRY와 별도 Runtime ARN을 호출하는 `lib/agentcore.ts` | 실제 원격 MCP의 도구 목록, 스키마, IAM과 응답을 별도 검증해야 한다. SQL 실행, DB 내부 접근 등 제외 작업도 섞여 있다. |
| **자동 복구가 리소스를 변경함** | `lib/k8s-watchdog.ts:52`의 ECS UpdateService(forceNewDeployment). `server.ts:55`에서 실제 타이머에 연결 | 읽기 전용 데모에 가져오지 않는다. |
| **권한 범위가 현재 요구보다 넓음** | `infra-cdk/lib/ecs-stack.ts:79`의 관리형 ReadOnlyAccess와 후속 AssumeRole 정책 | 기존 역할을 복사하지 않는다. 새 고정 도구별 액션을 별도 최소 정책으로 작성한다. |
| **캐시 데이터의 관측 메타데이터가 부족함** | `steampipe-client/src/client.ts:23`의 기본 300초 캐시, QueryResult는 rows/error | 캐시를 새 실조회처럼 표시하지 않는다. 원본 관측 시각, 조회 범위와 데이터 출처를 보강한다. |
| **이력 조회의 계정 구분과 오류 표현을 보강해야 함** | `repos/inventory.ts:21`, `:34`는 계정 필터 없이 최신/추세를 계산. `routes/inventory.ts:25`, `:41`는 DB 오류를 빈 200 응답으로 반환 | 계정과 리전으로 필터링하고, 빈 결과와 저장소 실패를 구분한다. |
| **일부 요약값은 실제 측정값이 아님** | `core/security.ts:5`의 `0 AS mfa_not_enabled`, `core/inventory.ts:31`의 숫자 변환 후 0 기본값 | 확인하지 않은 값은 미확인으로 남긴다. 0이나 정상으로 해석하지 않는다. |
| **비용 추정에 고정 가격이 있음** | `core/container-cost.ts:5`의 2025년 가격 상수 | 실제 청구와 추정을 분리하고, 적용할 가격과 리전을 다시 확인한다. README의 비용 예시도 현재 가격으로 인용하지 않는다. |
| **CloudTrail 원문에 민감한 필드가 포함됨** | `core/cloudtrail.ts:35`의 access_key_id, cloud_trail_event | 이벤트 이름/시각/대상 등 허용 필드만 내보내며 원문 전체를 모델에 보내지 않는다. |

현재 Steampipe Dockerfile에는 AWS와 Kubernetes 플러그인 설치가 있다.
Trivy 취약점 SQL은 존재하지만, 이 Dockerfile에서 Trivy 플러그인 설치는 확인하지 못했다.
따라서 취약점 데이터가 현재 환경에서 제공된다고 단정할 수 없다.

예약 보고서도 주의가 필요하다. `routes/report.ts:153`과 `server.ts:39`에 따르면 현재 경로는
API 프로세스 내부 타이머다. 과거 EventBridge의 단독 ECS 작업 경로는 Steampipe 접근 문제로
현재 저장 경로에서 동기화하지 않는다. 이 타이머를 Lambda Web Function으로 그대로 옮기지 말고,
별도 스케줄 실행과 중복 방지, 실패 기록을 설계해야 한다.

## 연결 방식

### 권장: 고정 도구로 기능 이식

현재 `APP_REGION=us-west-2`, `TARGET_REGION=ap-northeast-2`, STS 계정 검증과
`global.openai.gpt-6-luna` 설정을 유지한다.
awsops_v2의 SQL은 필요한 필드와 필터를 파악하는 참고 자료로 사용하고,
실제 조회는 Runtime의 서비스별 boto3 함수로 구현한다.

새 도구마다 공식 API/IAM 대응표, 허용 필드, 페이지/리소스 상한, 권한 거부와 부분 결과,
관측 시각을 먼저 정의한다. 이 문서는 새 AWS API의 권한 검증이나 구현 완료를 뜻하지 않는다.
ECR 실행 이미지 pull 권한처럼 오레곤 실행 인프라용 권한과 서울 리소스 조회 권한도 분리한다.

### 조건부: 기존 awsops_v2 API를 호출하는 어댑터

기존 배포 API를 활용할 수도 있지만 다음 연결 조건이 필요하다.

1. **접근 경로와 서비스 인증:** 현재 Steampipe는 ECS Service Connect의 내부 주소다.
   현재 Runtime이 내부 DNS나 포트에 접근할 수 있다고 가정하지 않는다. API 인증도
   Cognito ID 토큰 쿠키 방식이므로 현재 앱 접속 키를 그대로 사용할 수 없다.
2. **고정된 API만 허용:** VPC/볼륨 등 정해진 GET 경로와 입력만 허용한다.
   임의 URL, 모델 생성 SQL, 계정 선택, 수정/삭제 경로는 MCP에 노출하지 않는다.
3. **계정과 리전 고정:** 서버 설정에서 검증한 계정만 요청하고 반환 행의 범위를 확인한다.
   원격 서버가 사용한 AWS 실행 계정은 현재 Runtime의 STS 결과만으로 증명되지 않는다.
4. **출처 계약 보강:** `source_system`, 원본 관측 시각, 캐시 여부, 제한과 오류를 전달한다.
   Steampipe/REST 응답에 존재하지 않는 AWS API 이름이나 Request ID를 만들어 넣지 않는다.
5. **네트워크 변경은 별도 설계:** 리전 간 VPC Peering을 기본 생성하지 않는다.
   사설 HTTP나 DB 직접 접근을 선택한다면 최초 데모 범위 밖의 확장으로 다룬다.

인증 소스: [plugins/auth.ts](../../awsops_v2/apps/api/src/plugins/auth.ts).  
내부 서비스 구성: [infra-cdk/lib/ecs-stack.ts](../../awsops_v2/infra-cdk/lib/ecs-stack.ts).

## 권장 작업 순서

1. **VPC, EBS, ECR 조회:** 현재 MCP에 고정 조회 작업과 서비스별 근거를 추가한다.
2. **관계도와 보고서 포맷:** 조회된 ID로만 관계도를 만들고, 현재 보고서에서 DOCX/PPTX를 생성한다.
3. **S3, DynamoDB와 보안 구성 점검:** 객체/항목 데이터 접근 없이 구성 상태만 확인한다.
4. **이력과 예약 보고서:** 계정/리전/조회 범위가 같은 기록만 비교하고 별도 실행 수명주기를 둔다.
5. **비용, 로그, Kubernetes, 외부 데이터 소스:** 추가 과금, 네트워크, 인증과 조회 한도를 정한 후 별도 기능으로 확장한다.

이번 작업에서는 위 기능을 새로 연동하지 않았다. HTML 보고서 미리보기는 별도로 구현하고
현재 운영 데스크에 배포했으며, 그 검증은 [배포 기록](aws-deployment.md)에 정리한다.
