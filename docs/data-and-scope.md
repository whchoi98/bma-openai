# 데이터 처리, 네트워크, 한도와 미지원 범위

## 데이터가 처리되는 위치

1. 브라우저는 us-east-1 Web Function에 질문을 전달한다.
2. Web Function은 STS로 배포 계정을 확인한 뒤 us-east-1 Mantle에 BMA 세션을 생성한다.
3. BMA는 `openai.gpt-6-luna` 모델과 지정 SessionRole을 사용한다.
   모델이 선택한 조회 도구는 us-east-1 AgentCore Runtime의 STDIO MCP에서 실행한다.
4. MCP는 Runtime 자격증명의 실제 STS 계정을 매번 확인한 뒤 ap-northeast-2 제어 API를 호출한다.
   계정 불일치 또는 STS 실패이면 리소스 API를 호출하지 않는다.
5. MCP는 필요한 필드만 정규화해 반환한다. 모델에 전달한 서울 조회 정보는 us-east-1 BMA에서 분석한다.
6. 공개 답변 delta를 SSE로 브라우저에 전달하고, 최종 답변과 정규화된 근거를 us-east-1 S3에 저장한다.

선택 가능한 Converse 구현은 현재 배포에서 사용하지 않는다. 이를 별도로 활성화하면
`global.openai.gpt-6-luna` 글로벌 추론 프로파일을 사용하며 모델 처리는 us-east-1에 고정되지 않는다.
두 경로의 API와 데이터 처리 범위를 혼동하지 않는다.

Lambda 환경 변수·실행 역할 설정·KMS 설정, RDS 사용자명·접속 주소·비밀 참조,
EC2 태그·사설 IP, ECS 이벤트 원문, 알람 액션·설명, AWS 오류 메시지 원문을 결과에서 제외했다.
자격증명은 표준 AWS credential provider chain을 통해 사용하며 세션 설정에 그 값을 저장하지 않는다.
MCP 환경 설정에는 자격증명 환경 **변수의 이름**만 전달한다.

reasoning, analysis 메시지, command_execution 원문은 웹 이벤트나 보고서로 내보내지 않는다.
Converse 연속 도구 호출에 필요한 서명된 reasoning 블록은 같은 요청의 서버 메모리에서만 유지한다.
공개 답변과 지정 서버 `seoul_aws`의 정규화된 도구 결과만 저장·표시한다.
보고서의 리소스 이름·텍스트는 HTML로 실행되지 않도록 이스케이프한다.
브라우저는 react-markdown v10 + remark-gfm을 사용하고 raw HTML·위험한 링크를 실행하지 않는다.
원격 Markdown 이미지는 로드하지 않으며 OTF Bold 폰트와 OFL 라이선스도 앱에 포함한다.

## 운영 조사 경로

운영 조사에서는 Web Function이 S3에 질문을 예약하고 같은 us-east-1의 worker Lambda를 비동기로 호출한다.
worker는 BMA 세션을 만들거나 이어 쓰고 공개 진행 상태를 최대 초당 한 번 저장한다.
브라우저는 저장된 스냅샷을 SSE로 받아 완료 전부터 표시하고, 연결이 끊기면 같은 상태를 다시 읽는다.
내부 추론과 원문 명령 결과는 스냅샷에 저장하지 않는다.

worker의 직접 권한은 BMA 세션 API, 지정 세션 역할 PassRole, 앱 버킷의 제한된 상태와 로그뿐이다.
서울 조회 권한은 계속 Runtime에만 있다. 상태 경로는 `investigations/ACCOUNT/ap-northeast-2/`다.
재사용 근거는 원본 시각을 보존하고 출처 turn을 표시한다. 브라우저에는 마지막 조사 ID만 저장한다.
실행 300초, 함수 timeout 360초, 동시 worker 2개, 후속 질문 기간 6시간과 최대 10개 질문으로 제한한다.
상태는 7일 후 만료하며 Lambda 실행과 S3 상태 요청이 추가 비용 항목이다.
[세부 구조와 한도](bma-investigations.md).

## 화면 표시와 언어

화면 이름은 **AI-Powered AWS Operations Desk**다. 현재 모델의 이름과 실제 모델 ID를 표시한다.
한국어 지명은 버지니아 북부으로 통일하며, 답변 문장에서는 엠대시와 가운뎃점 같은 구분 기호를 정리한다.
리소스 식별자와 코드의 원문은 유지한다.

계정 ID는 화면에서 마지막 3자리만 표시한다. 계정 카드, 답변, 실행 기록과 웹 버튼으로
다운로드한 Markdown/HTML에 적용한다. 스트림 중간에 번호가 끊기거나 강조 표시로 나뉘어도 가린다.
JSON 조회 API 응답과 S3 원본 근거에는 전체 ID가 남는다.
STS 검증과 EXPECTED_ACCOUNT_ID 비교에는 원래 12자리 ID를 사용한다.

Markdown, HTML, DOCX, PPTX의 모든 보고서 응답은 서버에서도 계정 ID를 가린다.
도구 근거가 없는 실패 보고서도 서버의 배포 계정을 기준으로 처리한다.
미리보기는 인증된 보고서를 스크립트 실행이 허용되지 않은 iframe에 표시하며,
제목, 표, 목록은 기존 react-markdown 렌더러로 변환한다.
다운로드 파일에는 스타일, OTF 폰트와 OFL 라이선스를 함께 넣어 외부 접속 없이 열 수 있다.
보고서를 여는 작업은 저장된 결과를 읽으며, 리소스 조회나 모델 추론을 다시 실행하지 않는다.

다크 모드와 한국어/English 선택은 브라우저 localStorage에 저장한다. 접속 키와 계정 ID는
환경 설정으로 저장하지 않는다. `POST /api/chat`의 `language`는 `ko` 또는 `en`만 허용한다.
선택한 언어로 다음 답변과 Node.js 웹 보고서를 생성하며 기존 답변을 다시 번역하지 않는다.
스트림 오류 후 언어를 전환해도 부분 답변과 수집된 실행 기록은 유지한다.

## 원본 awsops에서 추가한 범위

VPC, EBS, ECR, S3, DynamoDB, ElastiCache, OpenSearch, MSK는 구성 정보만 조회한다.
공유 VPC와 보안 그룹은 STS 확인에 더해 반환된 소유자도 검증한다.
S3 상세는 소유 서울 버킷 목록의 정확한 이름과 ExpectedBucketOwner로 제한한다.
관계도는 실제 반환된 ID만 연결하며, 네트워크 통신 시험 결과로 해석하지 않는다.
보안 점검의 pass/fail/unknown은 개별 구성 기준이며 취약점이나 전체 보안 점수로 확대하지 않는다.

이력은 앱 버킷의 계정/대상 리전별 prefix에 보관한다. 페이지당 최대 20개, 화면은 최대 100개다.
리소스 수가 잘린 이전 보고서를 전체 자원 수의 추세로 비교하지 않는다.
기존 보고서 인덱싱은 한 번에 최대 200개이며 원본을 변경하지 않는다.
DOCX/PPTX는 입력 1 MB, 출력 4 MB, PPTX 최대 40개 슬라이드다.
PPTX 요약이 제한되면 안내를 표시하고 전체 마스킹 근거를 발표자 노트에 남긴다.
Office 문서는 NanumSquare 폰트를 지정하며 실제 폰트 표시는 열람 환경에 따른다.

## 저장과 보존

- 앱 결과는 S3 `runs/`에 저장한다. TLS, 공개 접근 차단, SSE-S3, 버전 관리를 사용한다.
  현재 버전은 7일, 비현재 버전은 1일 후 만료한다.
- BMA 서비스의 세션 데이터와 앱 S3 파일은 별도 수명주기이다. 앱 객체 만료가 BMA 세션 삭제를 뜻하지 않는다.
- 단일 질문은 질문마다 새 BMA 세션을 만든다. 운영 조사는 같은 세션을 최대 10개 질문에 사용한다.
  성공한 BMA 세션을 자동 삭제하지 않는다.
  서버 측 앱 상태의 `bma_session_id`로 운영자가 식별할 수 있다. 브라우저 완료 이벤트에는 이 ID를 내보내지 않는다.
- Converse 경로에는 BMA 세션이 없다. 한 질문의 도구 호출은 같은 Runtime 세션 ID를 사용한다.
  브라우저 연결 종료나 turn timeout에서 모델·Runtime·STS 요청을 중단한다.
  이미 실행 중인 원격 MCP는 bridge의 별도 90초 제한과 자식 프로세스 정리로 종료된다.
- Runtime idle timeout은 **900초**, 최대 lifetime은 **28,800초**이다.
  완료 후에도 idle 종료 전까지 실행 환경이 남을 수 있다. 세션 저장소나 S3 Files는 구성하지 않았다.
- 코드·이미지 버킷/ECR와 로그 그룹은 스택 삭제 시 Retain이다. 잔여 리소스 정리는 운영자가 관리한다.
- 로컬 샘플은 최근 20개 결과만 프로세스 메모리에 보관하며 재시작 시 사라진다.

## 네트워크

기본 Runtime은 **PUBLIC** 모드이다. 일반 AWS 제어 API를 위해 VPC Peering, Transit Gateway,
VPN, NAT Gateway, 데이터베이스 보안 그룹 변경을 생성하지 않는다.

필요한 outbound DNS/HTTPS(443) 대상은 버지니아 북부 Bedrock Runtime·AgentCore·Mantle·STS 및 서울의 EC2, RDS, ECS, Lambda,
CloudWatch API이다. 조회 리전은 클라이언트 `region_name`으로 정하며 VPC 연결 리전과 같은 개념이 아니다.
서울 API 호출 성공은 해당 실행 환경의 접속 근거이며, 로컬에서의 성공을 배포 Runtime 네트워크의
검증으로 확대해서 설명하지 않는다.

VPC 모드로 바꾸면 별도 egress 경로·DNS·프록시·엔드포인트 정책을 검증해야 한다.
DB SQL, 사설 HTTP, Kubernetes API는 제어 API 조회와 다르며 별도 라우팅·보안 그룹·인증이 필요하다.
이번 데모는 그런 내부 데이터 접근을 하지 않는다.

## 호출·비용 한도

| 항목 | 한도 |
| --- | --- |
| 도구별 리소스 | 최대 100개, 환경 변수로 낮출 수 있음 |
| 페이지 | 최대 10개, 반복 토큰 감지 |
| 도구별 SDK 호출 | STS 포함 최대 31개, 초과 시 부분 조회로 종료 |
| 재시도 | boto3 standard mode, 최초 요청 포함 최대 3회 |
| boto3 연결/읽기 timeout | 3초 / 10초 |
| EC2 건강 점검 | 최대 20 ID |
| ECS DescribeServices | 최대 10 서비스 |
| 지표 기간 | 최대 6시간, 최근 7일 이내 |
| 지표 포인트 | 최대 1,440개, 300초 버킷 |
| BMA 이벤트 스트림 | 기본 180초, 최대 600초 설정 |
| BMA 세션 생성 | 최대 120초, POST 자동 재시도 없음 |
| 이벤트 스트림 초기 연결 | 최대 3회, 일시 오류에만 5초·10초 간격 |
| BMA 완료 item 수집 | 최대 5 × 100 item, 별도 30초 제한 |
| BMA cancel 요청 | 별도 5초 요청 제한 |
| Converse 모델·도구 루프 | 최대 8회 모델 호출, 30회 도구 호출, 모델 응답당 4,096 토큰 |
| Converse 메시지 / 공개 답변 | 350 KB / 60,000자; 모델 reasoning은 라운드당 200 KB |
| MCP bridge | 요청 64 KiB, 실행 90초, Runtime 환경당 동시 4개 |
| STS AssumeRole | 지정 SessionRole만 사용, 요청 15초, turn 중단 신호 전파 |
| 앱 동시 조회 | Web 실행 환경당 2개, endpoint 최대 2개 환경 |
| Web endpoint rate limit | 100 요청/초; 현행 서비스의 최소 양수 단위 |
| 보고서 | 최대 4 MB 저장 |
| 로컬 live smoke | 서비스별 반환 최대 2개, 클러스터 1개, Lambda 1개의 15분 |

CloudWatch **GetMetricData는 과금 가능한 API**이다. 최대 4개 고정 지표/리소스만 조회하고
Metric math·Metrics Insights·로그 검색을 실행하지 않는다. 가격은
[CloudWatch 요금](https://aws.amazon.com/cloudwatch/pricing/)을 확인한다.
지표 포인트 한도는 비용의 금액 상한을 보장하지 않는다. AWS의 과금 단위와 요청·지표 수를 함께 확인한다.

실제 배포에는 BMA 또는 Converse 모델 추론, Web Functions, Runtime 컴퓨팅, S3, ECR,
CloudWatch 로그 및 해당 데이터 전송 비용이 발생할 수 있다. 글로벌 프로파일의 처리 위치도 고려해야 한다.
실제 AWS 배포·추론 검증의 적용 한도와 근거는
[AWS 배포 보고서](aws-deployment.md)에 구분해 기록했다.
정적 접속 키를 공유하는 데모이므로 사용자별 비용 할당이나 전역 분산 rate limiter는 제공하지 않는다.

## 결과를 해석하는 기준

`observed_at`는 도구가 시작된 UTC 시각이며 호출별 소요 시간을 함께 기록한다.
여러 페이지·서비스의 결과는 동일 시점의 원자적 스냅샷이 아니다.

지표 결과의 `service`는 관측 대상(예: Lambda)이며 실제 API 제공자는 `api_calls`에
CloudWatch로 기록한다. 보고서 범위에는 둘 다 반영한다. CloudWatch 지표 조회가
알람 목록 조회까지 수행했다는 뜻은 아니므로 도구명과 API별 범위를 함께 읽는다.

| 상태 | 의미 |
| --- | --- |
| `ok` | 요청한 범위에서 관측 결과를 얻음 |
| `empty` | API 조회 성공 후 해당 범위의 목록 또는 지표 데이터가 비어 있음 |
| `access_denied` | 권한 부족. 리소스가 없다는 뜻이 아님 |
| `unsupported_service` | 구현하지 않은 서비스의 지표 요청 |
| `api_error` | API/자격증명/지표 시리즈 실패 |
| `partial` | 일부 결과만 확보됨. 잘림, 개별 실패, 누락 등의 원인은 별도 필드 |
| `account_mismatch` | 실제 계정과 배포 기대 계정이 달라 조회 차단 |
| `invalid_input` | 허용 범위를 벗어나 리소스 API를 호출하지 않음 |

`pagination_complete`와 `truncated`는 별개이다. 다음 페이지에서 API가 실패하면
완료는 false이고 잘림은 false일 수 있다. 한도로 중단하면 잘림도 true이다.
get_account_context처럼 리소스 목록이 아닌 호출은 `resource_ids=[]`가 정상이다.
모든 시리즈가 성공한 빈 지표는 `no_data`이며 실제 값 0을 가진 데이터 포인트와 구분한다.

EC2/RDS/Lambda 구성 상태, EC2 인프라 상태 점검, ECS 태스크 수, CloudWatch 알람은 각각 다른 관측이다.
이 중 하나만으로 애플리케이션 정상이나 장애 원인을 판정하지 않는다.

## 미지원 범위

- 다른 계정·다른 리전, 자유 입력 AssumeRole, AWS 전체 서비스 인벤토리.
- S3 객체 내용과 directory buckets, DynamoDB 항목 Query/Scan.
- ElastiCache 서버리스/캐시 명령, OpenSearch Serverless/검색 문서, Kafka 토픽/메시지 조회.
- Lambda Web Functions 조회, Lambda 버전·별칭별 지표, Event source mapping 목록.
- RDS DB 클러스터 별도 목록·SQL·DB 엔진 내부 상태.
- ECS 태스크/컨테이너별 진단, EKS/Kubernetes API.
- 사설 HTTP/애플리케이션 합성 모니터링.
- CloudWatch 로그 검색·Metrics Insights·사용자 정의 지표·복합 알람 의존성 분석.
- 비용 분석·Cost Explorer·청구 데이터.
- 리소스 생성·수정·삭제·중지·재시작 MCP.

이 항목들은 Skill로 권한을 부여해 우회하지 않는다. 확장 시 구현 API·IAM·네트워크·인증·한도와
추가 과금 항목을 먼저 정하고 별도 검증해야 한다.
