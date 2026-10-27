# 검증 결과

## BMA 운영 조사 추가 검증

최신 로컬 검사: Python 302개, Node.js 206개, 총 508개 통과.
실제 같은 BMA 세션의 세 질문, 원본 근거 재사용, 연결 중단 복구, 이전 인스턴스 ID를 사용한 추가 점검을 확인했다.
브라우저 완료 전 새로고침 후 같은 조사로 복귀했고 추가 POST는 0회였다.
절차 네 가지, 버전 표시, 계정 마스킹, 두 언어/테마, 모바일, HTML 미리보기와 네 가지 파일 형식을 검증했다.

[새 기능 검증 결과](../artifacts/investigations/summary.json), [사용 방법](bma-investigations.md).

## 2026-10-27 us-east-1 BMA 이전 검증

현재 배포는 `us-east-1`, 모델은 Mantle의 `openai.gpt-6-luna`, 조회 대상은 `ap-northeast-2`다.
기존 오레곤 배포를 삭제했으며 아래의 오레곤 기록은 과거 검증으로 보존한다.

- Python 278개, Node.js 73개: 총 351개 통과.
- 실제 BMA 조회 9건: MCP 도구 24개 전부 실행, 도구 결과 37건, AWS 요청 ID 72개.
- 공개 SSE 답변 delta 5,255개, 두 언어에서 완료 전 Markdown 렌더링 확인.
- API 오류와 권한 오류 0건. 잘린 목록은 부분 조회, 비어 있는 지표는 데이터 없음으로 유지.
- 실제 IAM 시뮬레이션 18개와 이전 배포 부재 확인 12개 통과.
- HTML 미리보기, DOCX/PPTX를 포함한 네 형식 다운로드, 이력과 관계도, 마스킹, 테마와 모바일 검사 통과.
- 원본 awsops 파일 20개는 변경하지 않았으며 공식 Runtime lifecycle 해시도 유지.

[현재 배포 보고서](aws-deployment.md), [검증 집계](../artifacts/migration-east/summary.json),
[로컬 검증](../artifacts/migration-east/local-verification.json),
[실제 BMA 연결](../artifacts/migration-east/bma-runtime-linkage.json).

검증일: **2026-10-26~27 UTC**.
최신 원본 awsops 추출 기능은 **Python 274개 + Node.js 71개, 총 345개** 회귀 검사와
세 실조회 흐름, 이력 재열기, 네 가지 문서 다운로드 검증을 통과했다.
최신 결과는 [추출 E2E 기록](../artifacts/e2e-extraction/summary.json)에 있다.
최초 구현의 로컬 검증 결과와 이후 AWS 배포 검증을 함께 기록한다.
**AWS 배포와 실제 Web Function → BMA → Runtime → MCP 종단 간 5개 시나리오가 통과했다.**
11개 MCP 도구·실제 AWS 요청 ID 27개·보고서 저장과 다운로드를 확인했다.
후속 요청에 따른 현재 `global.openai.gpt-6-luna` Converse 경로에서도
같은 5개 시나리오·11개 도구·27개 요청 ID와 실제 브라우저의 완료 전 Markdown 표시를 확인했다.
접속 정보와 상세 근거는 [AWS 배포 보고서](aws-deployment.md)에 있다.
화면, 언어, 계정 마스킹 변경 후 회귀 검사는 **Python 110개 + Node.js 31개, 총 141개 통과**했다.
이후 HTML 보고서 미리보기 변경에서는 **Node.js 34개**와 브라우저 검사를 통과했다.

## 로컬 검증

| 항목 | 결과 | 근거 |
| --- | --- | --- |
| Python / Stubber / IAM·배포 입력 / MCP bridge | 110 passed, 실패·건너뜀 0 | `artifacts/ui-python-tests.log` |
| Node.js / Converse / BMA / Markdown / 표시 변환 | 31 passed, 실패 0 | `artifacts/ui-final-validation.log` |
| Python 정적 검사 | 통과 | `artifacts/ruff-streaming.log` |
| MCP STDIO | initialize → tools/list → tools/call 통과, 도구 24개 | `tests/test_mcp.py`, Runtime probe |
| Skills | 4개, 보안 구성 점검 포함 | Runtime probe |
| 브라우저 | 예제 질문 5개, Markdown·HTML 다운로드 통과 | `artifacts/browser-check.json` |
| 화면 | 1440×1050, 390×844; 수평 넘침·JavaScript 오류 없음 | `artifacts/ui-desktop.png`, `artifacts/ui-mobile.png` |
| 스트리밍 Markdown 화면 | 완료 전에 제목·표·목록·코드 렌더링, 원격 이미지·위험한 HTML 차단 | `artifacts/markdown-browser-check.json` |
| 나눔스퀘어 OTF Bold | 로컬 OTF 로드, 700 굵기, 모바일 수평 넘침 없음 | `artifacts/markdown-streaming-desktop.png`, `artifacts/markdown-mobile.png` |
| Runtime 컨테이너 | ARM64 빌드, UID 1000, Codex 0.164.0, Skills 4개, /ping Healthy | `artifacts/extraction-runtime-build.log`, `artifacts/runtime-probe.json` |
| 컨테이너의 MCP | 네트워크 차단 상태에서 기존 BMA lifecycle + HTTP→STDIO MCP 호출 통과 | `artifacts/runtime-probe.json` |
| Web Function ZIP | Node.js 24 패키지 생성·ZIP CRC 확인 | `artifacts/web-build.json` |
| CloudFormation | 두 템플릿 AWS ValidateTemplate 통과 | `artifacts/cloudformation-validation.json` |
| CloudFormation lint | 오류 0, 알려진 BMA preview 권한 카탈로그 경고 6개 | `artifacts/cfn-streaming.log` |

Python 참조 웹 앱의 TestClient에서 Starlette/httpx 사용 중단 예정 경고 1개가 발생한다.
테스트 실패는 없으며 배포 서버는 Node.js이다.

`cfn-lint`의 6개 W3037은 RegisterEnvironment, ConnectEnvironment 및 네 가지 BMA 세션 호출이
도구의 IAM action 카탈로그에 아직 등록되지 않아 발생한다.
이 액션은 [공식 BMA 보안 문서](https://docs.aws.amazon.com/bedrock/latest/userguide/bedrock-managed-agents-openai-security.html)와
공식 예제의 권한 목록으로 대조했다. 경고를 없애기 위해 IAM 권한을 확대하거나 문서화된 액션을 제거하지 않았다.
최종 lint는 `--non-zero-exit-code error`로 실행했으며 경고 원문은 로그에 보존했다.

## 검증한 실패·경계 조건

- 환경의 AWS_REGION과 무관하게 BMA·STS는 us-west-2, 조회는 ap-northeast-2를 사용.
- STS 계정 불일치·검증 실패에서 지역 리소스 호출 차단.
- 질문의 계정·리전·모드·임의 작업 인자를 수용하지 않음.
- 중첩 EC2 응답의 페이지네이션, 정확히 상한에 도달한 완전한 결과, 페이지 중간 잘림,
  반복 토큰, 후속 페이지 API 실패 시 기존 결과 보존.
- 권한 거부와 빈 결과 구분, ECS 전부 거부와 일부 실패 구분.
- 실제 0 데이터 포인트와 지표 없음 구분, 모든 지표 실패와 부분 실패 구분,
  불완전한 페이지를 완전한 시리즈로 표현하지 않음.
- Lambda 환경 변수·역할·KMS 설정, RDS 접속 주소·사용자·비밀 참조,
  EC2 태그·사설 IP, ECS 이벤트 원문, 알람 액션·오류 원문 제거.
- SDK 실패 재시도가 최초 시도 포함 3회에서 종료됨.
- BMA 스트림의 `stream=true`와 SigV4 서명, UTF-8/다중 행 SSE,
  내부 추론·셸 출력 제거, 지정 MCP 서버 결과만 수용.
- STS 실패·스트림 실패 시 item 재조회보다 먼저 중단 요청.
- 브라우저 연결 종료 시 BMA 중단 요청, item 재조회 실패 시 이미 수신한 근거 보존.
- Converse 공개 텍스트 delta를 완료 전 전달하고 내부 reasoning은 표시하지 않음.
- Converse 계정 불일치 시 모델 추론 전에 중단, STS 자격증명 획득 중에도 turn 취소 적용.
- 스트림 도중 실패 시 부분 답변 유지, 연속 호출용 opaque reasoning 청크는 손실 없이 결합.
- MCP bridge의 요청 크기·잘못된 청크·실행 제한 시간과 자식 세션 정리.
- 접속 키가 없으면 모든 `/api/` 경로 차단.
- HTML 보고서에서 입력 마크업을 실행하지 않음.
- Runtime 역할에서 리소스 변경·미지원 조회·AssumeRole을 허용하지 않음.
  Web 역할에 서울 조회 권한이 없고, 세션 역할의 모델·Runtime·PassRole 범위가 제한됨.

독립 코드 검토에서 확인한 스트림 옵션, 중단 순서, STS 실패 처리, 전부 거부/실패 상태 분류,
Web endpoint의 허용 rate limit 단위를 수정하고 회귀 테스트를 추가했다.

## 2026-10-27 화면 변경

- 이름을 **AI-Powered AWS Operations Desk**로 변경했다.
- Luna와 실제 모델 ID를 함께 표시한다.
- 다크 모드와 한국어/English 전환, 브라우저 재시작 후 설정 유지를 검증했다.
- 영어 요청은 모델 지침에 반영되고, Node.js 웹 보고서도 영어로 생성된다.
- 계정 ID는 화면과 웹 다운로드에서 마지막 3자리만 표시한다.
  강조 구문과 하이픈으로 나뉜 번호, 중단된 부분 번호도 가린다.
  비슷한 숫자로 끝나는 EC2 리소스 ID는 변경하지 않는다.
- 스트림 오류 후 언어를 전환해도 부분 답변과 실행 기록을 보존한다.
- 문장의 엠대시와 가운뎃점을 제거하며, 식별자와 코드의 원문은 유지한다.
- 접속 전 오류 메시지와 예제 질문 버튼도 선택한 언어로 동작한다.

브라우저 근거: [화면 검증](../artifacts/ui-preferences-check.json),
[영어 다크 모드](../artifacts/ui-preferences-dark-en.png).
배포 패키지의 마지막 브라우저 검증은 `artifacts/ui-release-validation.log`에 기록한다.

AWS의 활성 Web Revision `rev-7ofiq`, Runtime 버전 3에서도 한국어와 영어로
ALARM 알람을 각 최대 2개 조회했다. 두 언어의 마스킹, 모델 표시, 완료 전 렌더링,
테마 유지와 총 4개 보고서 다운로드를 확인했다. 실제 AWS 요청 ID는 6개다.
근거: [실제 UI 검증](../artifacts/e2e-ui/summary.json).

## HTML 보고서 미리보기

- 저장된 보고서의 Markdown 본문을 HTML 제목, 표와 목록으로 렌더링한다.
- 미리보기와 HTML 다운로드 전용 응답은 서버에서 계정 ID를 가린다.
  도구 근거가 없는 실패 보고서도 배포 계정 번호를 노출하지 않는다.
- 한영 표시, 라이트/다크 테마, 모바일 크기, Esc로 닫기와 포커스 복귀를 확인했다.
- 지연된 다운로드 중 새 조회가 끝나도 원래 보고서의 내용과 파일명을 유지한다.
- 스크립트와 원격 이미지를 실행하지 않는다.
- 다운로드한 파일에 스타일, 폰트와 OFL 라이선스가 포함되며 외부 요청 없이 렌더링된다.
- 실제 AWS의 ALARM 조회를 한국어와 영어로 실행한 뒤 두 보고서의 미리보기와 다운로드를 확인했다.

HTML 미리보기 검증 당시 Web Revision은 `rev-sfebb`였다. 이 단계에서는 Runtime 및 조회 권한을 변경하지 않았다.
근거: `artifacts/html-preview-license-checks.log`,
[브라우저 검사](../artifacts/ui-preferences-check.json),
[실제 미리보기 검증](../artifacts/e2e-report-preview/summary.json).

## 제한된 실제 AWS 조회

- STS로 확인한 계정: **`*********239`**
- 대상: **ap-northeast-2**
- 관측 UTC: **2026-10-26T15:25:06Z ~ 15:25:09Z**
- Asia/Seoul 표시: **2026-10-27 00:25:06 ~ 00:25:09 KST**
- 실행 주체: **현재 로컬 AWS 자격증명**. 배포된 Runtime 역할의 실행으로 표시하지 않는다.
- 한도: 서비스별 반환 최대 2개, ECS 클러스터 1개에 속한 서비스,
  Lambda 함수 1개의 최근 15분 지표.

| 도구 | 실제 결과 | 반환 기록 | 잘림 |
| --- | --- | ---: | --- |
| get_account_context | ok, 기대 계정 일치 | 계정 문맥 1개 | false |
| list_ec2_instances | partial | 인스턴스 2개 | true |
| get_ec2_instance_health | ok | 상태 점검 2개 | false |
| list_rds_instances | partial | DB 인스턴스 2개 | true |
| list_ecs_clusters | partial | 클러스터 2개 | true |
| list_ecs_services | ok, 첫 클러스터만 조회 | 서비스 2개 | false |
| get_ecs_service_health | ok | 서비스 2개 | false |
| list_lambda_functions | partial, Event Functions | 함수 2개 | true |
| get_lambda_function_health | ok | 함수 1개 | false |
| get_resource_metrics | empty | 함수 1개, 지표 4종, **데이터 포인트 0개** | false |
| list_cloudwatch_alarms | partial, ALARM 필터 | 알람 2개 | true |

목록의 `partial`은 설정한 소규모 상한으로 인한 의도적인 잘림이다.
전체 자원 수나 조회하지 않은 클러스터 상태를 이 수치로 추정하지 않았다.
Lambda 지표 없음은 오류 0건·스로틀 0건·정상으로 바꾸지 않았다.

ARN/ID·API·UTC 시각·페이지 상태·정규화된 필드의 원본 근거는
[live-smoke.json](../artifacts/live-smoke.json)에 있다.
[Markdown](../artifacts/live-smoke.md)과 [HTML](../artifacts/live-smoke.html) 보고서도 생성했다.
이 파일들은 Git과 소스 배포 묶음에서 제외한 로컬 검증 산출물이다.

us-west-2 Mantle `/v1/models`의 모델 목록 조회도 성공했다.
목록 조회가 모델 추론 또는 BMA 세션 실행 검증을 뜻하지는 않는다.

## 네트워크 확인

로컬에서 실행한 Runtime 컨테이너의 DNS·TCP·TLS 연결로 서울의 EC2, RDS, ECS, Lambda,
CloudWatch 엔드포인트 5개에 접근할 수 있음을 확인했다.
이 검사는 자격증명이나 리소스 데이터를 전송하지 않는 TLS 연결 검사이다.
근거: `artifacts/container-network.json`.

로컬 호스트·Docker에서의 성공을 us-west-2에 배포된 AgentCore 네트워크의 검증으로
확대하지 않는다. 기본 IaC는 PUBLIC Runtime이며 Peering/VPC/NAT를 생성하지 않는다.

## 이후 완료한 배포 검증

이 문서의 로컬 검증 후 사용자의 배포 요청에 따라 다음을 실제 수행했다.

- ECR push, 버전이 고정된 비공개 S3 코드 업로드, CloudFormation 배포.
- 실제 Web Function URL의 인증·조회 스트림·보고서 저장과 다운로드.
- BMA 추론, Runtime V2 활성화, 환경 기반 STDIO MCP 연결.
- 배포된 Runtime 역할로 서울의 EC2·RDS·ECS·Lambda·CloudWatch 조회.
- Runtime·Web·세션 역할의 실제 IAM 정책 범위 시뮬레이션.

상세 결과: [종단 간 검증 JSON](../artifacts/e2e/summary.json),
[배포 보고서](aws-deployment.md).

## 2026-10-26 모델·스트리밍·폰트의 배포 검증

- 당시 활성 Web Revision: `rev-fxhsu`, 트래픽 100%, `AGENT_BACKEND=converse`.
- 실제 모델: `global.openai.gpt-6-luna`. 앱·Runtime은 us-west-2, 조회는 ap-northeast-2.
  글로벌 모델 처리 범위는 UI·MCP 계정 문맥·두 보고서에서 표시한다.
- EC2·RDS, EC2 점검, ECS, Lambda, CloudWatch ALARM을 실제 웹에서 검증했다.
  원본 도구 관측 시각은 2026-10-26 23:32:28~23:34:08 UTC이다.
- 공개 text delta 총 3,164개. 모든 CLI 사례에서 완료 전에 delta를 받았고,
  실제 Chromium의 DOM에서도 완료 전에 Markdown을 표시했다.
- 실제 브라우저에서 나눔스퀘어 OTF Bold의 로드 및 700 굵기를 확인했다.
  모바일 수평 넘침·JavaScript 오류는 없었다.
- Markdown·HTML 총 10개 다운로드 확인. 지표 없음은 0건이나 정상으로 바꾸지 않았다.
- 기존 BMA 모델로 새 Runtime의 STDIO MCP 연결과 delta 306개도 별도 확인했다.
  이 재검사는 로컬 BMA 클라이언트이며 현재 Web Function의 추론 경로와 구분한다.

근거: [현재 E2E 결과](../artifacts/e2e-converse/summary.json),
[실제 배포 설정·IAM](../artifacts/deployed-streaming-proof.json),
[BMA 호환성](../artifacts/e2e/bma-streaming-compatibility.json).

## 수행하지 않은 범위

VPC 모드·사설 네트워크·서비스 내부 데이터 접근, 모든 리소스에 대한 전수 검증은 수행하지 않았다.
전체 미지원 범위는 [데이터 처리와 범위](data-and-scope.md)를 참고한다.
