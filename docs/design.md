# 서울 리전 AWS 리소스 조회 데모 설계

> 이 문서는 최초 설계 또는 오레곤 추출 검증 기록을 포함합니다. 현재 실행 리전과 모델은 [배포 보고서](aws-deployment.md)를 기준으로 확인합니다.

## 기준과 범위

2026-10-26 사용자 요구사항을 구현한다. 공식 BMA 예제의 Runtime 연결과
Lambda Web Functions의 HTTP 서버 실행 규약을 따른다.
후속 요청에 따라 지정 글로벌 모델·ConverseStream·SSE·React Markdown 렌더링을 추가했다.

- 실행: `APP_REGION=us-west-2`. BMA 서명, Runtime 및 앱 저장소에 적용한다.
- 조회: `TARGET_REGION=ap-northeast-2`. EC2, RDS, ECS, Lambda Event Functions,
  CloudWatch 클라이언트에만 적용한다.
- 계정: 배포 주체의 STS 결과로 고정한 `EXPECTED_ACCOUNT_ID`를 Runtime에 설정한다.
  매 도구 실행마다 같은 자격증명 체인으로 STS를 확인한다. 불일치·검증 실패 시
  리소스 API를 호출하지 않는다.
- MCP: 공식 BMA의 `agent.tools[].transport.type=stdio`를 사용한다.
  Converse 경로도 동일한 STDIO MCP 서버를 제한된 HTTP bridge를 통해 호출한다.
  명시적으로 등록된 조회 함수만 노출한다. 임의 AWS 작업·셸 도구는 추가하지 않는다.
- Lambda `ListFunctions`는 Event Functions 목록이며 Web Functions 목록은 제외한다.

## 구성

두 추론 경로를 서버 설정 `AGENT_BACKEND`로 선택한다.

- `bma`: 브라우저 → Web Function → us-west-2 BMA 세션 →
  us-west-2 Runtime V2 exec-server → STDIO MCP → 서울 AWS 제어 API.
- `converse`: Web Function → 지정 SessionRole의 ConverseStream 호출과
  Runtime InvokeAgentRuntime 호출 → 제한된 HTTP bridge → STDIO MCP → 서울 AWS 제어 API.
  모델이 반환하는 도구 호출을 Web Function이 중개하며 AWS 조회 자체는 Runtime에서 실행한다.

Runtime 이미지에 조회 코드와 3개 Skills를 포함한다. Skills는 절차만 안내하며,
실제 읽기 전용 경계는 도구 레지스트리·입력 검증·IAM 허용 목록이다.
Converse 경로에는 같은 Skills의 내용과 SHA-256을 빌드 계약에 포함해 시스템 지침으로 전달한다.
BMA 경로의 모델 전달 정보는 us-west-2 BMA에서 분석한다.
`global.openai.gpt-6-luna` Converse 경로는 글로벌 프로파일이므로 처리 리전이 오레곤에 고정되지 않는다.
PUBLIC Runtime의 HTTPS egress를 기본으로 하며 리전 간 VPC Peering은 만들지 않는다.

## 결과 계약

각 결과는 account_id, region, service, observed_at(UTC), api_calls,
resource_ids, pagination_complete, truncated, errors, permission_denied,
status, count, data, duration_ms, mode를 갖는다. 데이터는 필드 허용 목록으로
정규화한다. 자격증명·Lambda 환경 변수·DB 접속 주소·원문 오류 메시지는 전달하지 않는다.

`ok`, `empty`, `access_denied`, `unsupported_service`, `api_error`,
`partial`, `account_mismatch`, `invalid_input`를 구분한다.
CloudWatch의 데이터 없음과 API 부분 반환은 각각 기록한다.
구성 상태와 애플리케이션 정상 여부를 분리한다.

## 권한과 앱

Web Function 역할은 BMA 호출, 지정 세션 역할 PassRole/AssumeRole, 앱 상태 저장만 수행한다.
세션 역할은 선택 모델 추론과 지정 Runtime invoke/stop만 수행한다.
Runtime 실행 역할에는 등록·연결·실행 인프라 권한과 서울 조회 정책을 별도 부여한다.
서울 조회 조건을 BMA·앱 저장소 권한에 적용하지 않는다.

공식 Web Functions 런타임이 Node.js 24만 지원하므로 실제 배포는 `web/`의 Node.js 서버를 사용한다.
Python `webapp/`는 로컬 참조 구현·계약 생성·검증 보고서용이다.
화면은 서버가 확인한 계정, 두 리전, 실제/샘플 모드, 지원 범위 및 시각을 표시한다.
실행 기록은 MCP 결과에서 추출하며 reasoning/command_execution 원문은 노출하지 않는다.
보고서는 정규화된 근거에서 Markdown과 HTML로 생성하고 UTC와 KST를 함께 표시한다.
모델의 공개 text delta만 SSE로 전달한다. 답변 영역은 react-markdown v10 + remark-gfm으로
부분 Markdown을 렌더링하며, 나눔스퀘어 OTF Bold와 라이선스를 로컬 정적 자산으로 제공한다.
원격 이미지·raw HTML·위험한 URL은 실행하지 않는다. 중단된 스트림의 부분 답변과 오류도 보존한다.

## 검증

Stubber와 고정 BMA 응답으로 계정·리전·페이지네이션·부분 실패·결측·민감 필드 제거를
검증한다. MCP STDIO 통합, BMA 요청 스키마, 화면/API 및 보고서 escaping도 확인한다.
라이브 검증은 STS, 서비스별 최대 소수 리소스, 짧은 지표 기간으로 한정한다.
배포·모델 호출이 실제 수행되지 않으면 검증 보고서에 별도로 명시한다.
