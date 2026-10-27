# 오레곤 배포의 보관 기록

이 배포는 us-east-1 이전으로 삭제되었습니다. 아래 내용은 삭제 전의 검증 기록입니다.

# AWS 배포 및 종단 간 검증

**2026-10-27 UTC 기준 원본 awsops에서 선택한 세 기능을 AI-Powered AWS Operations Desk에 배포했다.**
VPC/EBS/ECR 조회와 관계도, 보고서 이력과 DOCX/PPTX, 추가 인벤토리와 보안 구성 점검을 제공한다.
현재 24개 MCP 도구, 13개 서비스 표시 범주, 4개 Skills를 사용한다.
Luna 모델, 다크 모드, 한국어/영어 전환, 계정 ID 마스킹과 문체 정리를 적용했다.
최초 Web Function → Converse 모델·Runtime V2 → MCP → 서울 AWS API 경로의
5개 시나리오에서 11개 MCP 도구와 실제 AWS 요청 ID 27개를 확인했다.
화면 개선 시 회귀 검사 **141개(Python 110, Node.js 31)**를 통과했고,
HTML 미리보기 변경 후에는 **Node.js 34개**와 두 언어의 실제 조회, 미리보기, 다운로드를 추가 검증했다.
기존 BMA 경로의 검증 기록은 보존했으며, 새 Runtime에 대한 BMA 호환성도 재검증했다.

## 접속

- 웹 주소: https://4tyhht7kxx15sh9x.vft.lambda-web.us-west-2.on.aws
- 접속 키 파일: `artifacts/deployment-secrets.json`의 `app_access_token`
- 파일 권한: `0600`. 키는 웹의 **접속 키** 입력란에 입력한다.
- 접속 키는 소스 ZIP, 브라우저 번들, 이 문서에 포함하지 않는다.

인증하지 않은 `/api/` 요청은 401이다. 실제 Chromium에서도 인증 후 계정 ID와
**실제 AWS 조회** 모드, 현재 모델, 글로벌 처리 범위, Markdown·HTML 다운로드를 확인했다.
스크린샷: [한국어 라이트 모드](../artifacts/e2e-ui/ko-light-desktop.png),
[영어 다크 모드](../artifacts/e2e-ui/en-dark-desktop.png),
[모바일](../artifacts/e2e-ui/en-dark-mobile.png).

## 배포 구성

| 항목 | 실제 값 |
| --- | --- |
| 계정 | `*********239` |
| 앱·Runtime 실행 및 API 호출 리전 | `us-west-2` |
| 조회 대상 리전 | `ap-northeast-2` |
| 현재 추론 경로 | `AGENT_BACKEND=converse`, `ConverseStreamCommand` |
| 현재 모델 | `global.openai.gpt-6-luna` |
| 모델 처리 범위 | 글로벌 추론 프로파일; us-west-2에 고정되지 않음 |
| 선택 가능한 기존 BMA 모델 | `openai.gpt-5.6-luna` |
| Runtime | `bma_seoul_inventory-ct66jiDWBf`, **플랫폼 V2 / 버전 4 / READY / PUBLIC** |
| Runtime 역할 | `bma-seoul-inventory-RuntimeRole-9rqCxCCRBhq5` |
| BMA 세션 역할 | `bma-seoul-inventory-SessionRole-CCwrzrXT4wJ0` |
| Web Function 역할 | `bma-seoul-inventory-WebRole-bmEfu8WwRrIc` |
| Web Function | `bma-seoul-inventory-web`, Node.js 24 |
| 활성 Web Revision | `rev-ym0mc`, 트래픽 100% |
| 배포 스택 | `bma-seoul-build`, `bma-seoul-inventory` |
| 결과 버킷 | `bma-seoul-inventory-appstate-odwefxoldgxt`, us-west-2 |
| 접속 방식 | HTTPS, ApplicationManaged + 앱 접속 키 |

최종 스택 상태는 `UPDATE_COMPLETE`이다. 정확한 ARN, 코드 버전, 이미지 digest는
[배포 기록](../artifacts/aws-deployment.json)에 있다.

## 원본 awsops 추출 기능 검증

원본 `/home/ec2-user/my-project/awsops`에서 추출했고, 기록한 원본 파일 20개의 해시가 유지됨을 확인했다.
로컬 회귀 검사 **345개(Python 274, Node.js 71)**와 Runtime 컨테이너, 브라우저 검사를 통과했다.

| 실제 검증 | 실행 범위 | 결과 |
| --- | --- | --- |
| 네트워크 | 소유 VPC 목록과 첫 VPC 관계도, EBS/ECR 목록 | 통과, 도구별 최대 2개와 잘림 표시 |
| 추가 구성 | S3/DynamoDB/ElastiCache/OpenSearch/MSK 목록, 반환된 첫 S3/DynamoDB/OpenSearch 상세 | 통과 |
| 보안 구성 | 첫 소유 VPC의 보안 그룹, EBS/RDS 구성 | 통과, 구성 기준과 앱 정상 여부 구분 |
| 이력/문서 | 위 저장 결과를 다시 열고 Markdown/HTML/DOCX/PPTX 다운로드 | 통과, 추가 모델/리소스 조회 0회 |

새 도구 13개 모두 실제 Runtime 역할로 실행했다. 전체 검증에서 도구 결과 19개,
실제 AWS 요청 ID 42개를 확인했고 권한 오류와 API 오류는 없었다.
관측 범위는 **2026-10-27 03:03:51~03:07:01 UTC**, **12:03:51~12:07:01 Asia/Seoul**이다.
모든 결과는 한정된 조회 범위이며 계정 전체 자원 수나 전체 보안 판정이 아니다.

기존 보고서 28건을 확인해 27건을 이력에 등록했다.
계정/리전 범위를 증명할 근거가 없는 1건은 건너뛰었고 원본은 유지했다.
실제 역할 시뮬레이션 16건으로 조회 범위와 쓰기/타 계정/타 리전 차단을 확인했다.

근거: [추출 기능 E2E](../artifacts/e2e-extraction/summary.json),
[실제 이력/문서 브라우저](../artifacts/e2e-extraction/browser.json),
[권한 검증](../artifacts/extraction-iam-proof.json),
[원본 파일 검증](../artifacts/awsops-extraction-provenance.json).
기능과 미지원 범위는 [추출 기록](awsops-extraction.md)에 있다.

## HTML 보고서 미리보기 검증

조회 완료 후 **HTML 보고서 보기**로 저장된 보고서를 렌더링한다.
본문의 Markdown도 제목과 표로 표시하며, 미리보기 창에서 HTML 다운로드와 닫기가 가능하다.
현재 테마를 적용하고, 계정 ID는 마지막 3자리만 보여준다.
스타일, OTF 폰트와 OFL 라이선스를 내장한 다운로드 파일도 외부 요청 없이 열리는지 확인했다.

한국어 라이트 모드와 영어 다크 모드에서 각각 ALARM 알람을 최대 2개 조회해 실제 보고서를 만들었다.
미리보기의 표, 계정 마스킹, 모바일 크기와 다운로드를 검증했다.
HTML 미리보기 단계에서는 Runtime 버전 3을 유지하고 Web Function 코드만 갱신했다.

근거: [HTML 미리보기 E2E 결과](../artifacts/e2e-report-preview/summary.json),
[한국어 미리보기](../artifacts/e2e-report-preview/ko-html-preview.png),
[영어 미리보기](../artifacts/e2e-report-preview/en-html-preview.png).

## 현재 화면의 실제 검증

한국어 라이트 모드와 영어 다크 모드에서 각각 ALARM 상태 알람을 최대 2개 조회했다.
두 요청 모두 `get_account_context`와 `list_cloudwatch_alarms`만 실행했다.
실제 AWS 요청 ID 6개와 공개 텍스트 delta 1,187개를 확인했다.
조회 시각은 2026-10-27 **00:49:55~00:50:31 UTC**, **09:49:55~09:50:31 Asia/Seoul**이다.

- 새 이름과 Luna, `global.openai.gpt-6-luna` 모델 ID가 표시된다.
- 계정 카드, 답변, 실행 기록과 웹 다운로드에서 계정 ID의 마지막 3자리만 보인다.
- 두 언어 모두 답변 완료 전에 Markdown이 표시된다.
- 답변 문장에 엠대시, 가운뎃점과 이전 지명 표기가 없음을 확인했다.
- 다크 모드와 언어 설정은 새로고침 뒤에도 유지된다.
- 각 언어의 Markdown과 HTML을 다운로드했으며, 두 화면 크기에서 넘침이나 JavaScript 오류가 없다.

서버의 계정 검증과 저장된 근거는 원본 ID를 사용한다. 이번 화면 검증은 CloudWatch 범위이며,
아래 최초 5개 서비스 시나리오 검증과 구분한다.
근거: [화면 E2E 결과](../artifacts/e2e-ui/summary.json),
[활성 배포 설정](../artifacts/ui-deployment-proof.json).

## 모델 경로와 화면 변경

실제 BMA CreateAgentSession에서 `global.openai.gpt-6-luna`는 HTTP 400,
`Model not found`를 반환했다. 같은 계정의 us-west-2 ConverseStream 호출은 성공했고,
GetInferenceProfile의 상태는 ACTIVE였다. 따라서 요청 모델과 스트리밍 조합은
Converse 경로로 구현했다. 현재 웹 요청이 BMA 세션에서 실행되는 것으로 표시하지 않는다.
근거: [모델 호환성](../artifacts/model-compatibility.json).

WebRole이 지정 SessionRole을 AssumeRole해 모델과 Runtime을 호출한다.
Runtime의 전용 HTTP bridge가 실제 STDIO MCP 클라이언트로 조회 도구를 실행한다.
계정 검증에 성공한 뒤에만 모델을 호출하며, 조회 권한은 RuntimeRole에 남아 있다.
기존 BMA lifecycle 파일은 수정하지 않았다.

`contentBlockDelta.delta.text`를 SSE로 즉시 전달한다. 내부 reasoning은 표시하거나 저장하지 않는다.
브라우저는 react-markdown **10.1.0**과 remark-gfm **4.0.1**로 부분 답변을 렌더링한다.
나눔스퀘어 **OTF Bold** 원본과 OFL 라이선스를 앱에 포함했으며 외부 폰트 CDN을 호출하지 않는다.
스트림이 중단되면 이미 표시한 부분 답변과 오류를 유지한다.

## 실제 적용한 조회 한도

이번 검증 배포에는 기본 상한보다 작은 값을 적용했다. 같은 CloudFormation 파라미터가
Web Function과 Runtime에 전달되고, MCP는 Runtime의 설정을 상속한다.

| 설정 | 배포 값 |
| --- | ---: |
| MAX_RESOURCES | 2 |
| MAX_PAGES | 2 |
| MAX_METRIC_HOURS | 1 |
| MAX_DATAPOINTS | 100 |
| MAX_TURN_SECONDS | 300 |
| Converse 루프 | 최대 8회 모델 호출, 총 30회 도구 호출, 응답당 4,096 토큰 |
| MCP bridge | 64 KiB 요청, 90초 실행, Runtime 환경당 동시 4개 |
| BMA 세션 생성 HTTP 대기 | 선택 시 120초, 자동 재시도 없음 |
| Runtime idle / maximum lifetime | 900초 / 28,800초 |

따라서 리소스가 더 있는 목록은 의도적으로 `partial`, `truncated=true`를 반환한다.
이 값은 조회 실패나 전체 자원 수를 뜻하지 않는다.

## 최초 Converse 배포에서 통과한 종단 간 시나리오

모든 요청은 실제 Web Function의 `/api/chat`으로 보내 Converse 경로가 실행하도록 했다.
결과의 계정·리전, AWS API 이름·실제 요청 ID, 오류·권한 부족, 조회 한도,
S3 저장과 Markdown·HTML 다운로드를 검사했다.

| 시나리오 | 실행된 MCP 도구 | 결과 |
| --- | --- | --- |
| EC2·RDS 인벤토리 | get_account_context, list_ec2_instances, list_rds_instances | 통과, 각 2개 및 잘림 표시 |
| EC2 상태 점검 | get_account_context, list_ec2_instances, get_ec2_instance_health | 통과, 반환된 2개만 점검 |
| ECS 배포 상태 | get_account_context, list_ecs_clusters, list_ecs_services, get_ecs_service_health | 통과, 첫 클러스터의 서비스 2개 |
| Lambda 구성·지표 | get_account_context, list_lambda_functions, get_lambda_function_health, get_resource_metrics | 통과, 첫 함수 1개·최근 15분 |
| CloudWatch ALARM | get_account_context, list_cloudwatch_alarms | 통과, ALARM 목록 최대 2개 |

도구 관측 시간은 **23:32:28~23:34:08 UTC**이며, Asia/Seoul에서는 **2026-10-27 08:32:28~08:34:08 KST**이다.
각 원본 관측 시각은 개별 결과에 보존했다.

Lambda의 선택 함수는 실제로 지표 데이터가 없었다. 답변은 `no_data`와 데이터 포인트 0개를
표시했고, 오류 0건·스로틀 0건·정상으로 해석하지 않았다.
EC2 점검과 ECS 실행 태스크 수 역시 애플리케이션 정상 판정과 구분했다.

5개 요청에서 공개 답변 delta **3,164개**가 전달됐다. 실제 브라우저에서도 완료 이벤트 전에
Markdown이 화면에 표시됐고, OTF 로드·700 굵기·모바일 수평 넘침 없음·JavaScript 오류 없음을 확인했다.
Markdown과 HTML은 총 10회 다운로드해 확인했다.

종합 근거: [최초 Converse E2E 결과](../artifacts/e2e-converse/summary.json).
개별 JSON·Markdown·HTML은 `artifacts/e2e-converse/`에 있다.
전체 지역 자원을 검증한 것이 아니라 위 서비스·리소스·기간만 검증했다.

### 보존한 BMA 경로

최초 BMA 배포의 5개 시나리오·11개 도구·27개 AWS 요청 ID 검증은
[기존 BMA E2E 결과](../artifacts/e2e/summary.json)에 남아 있다.
후속 변경 후에는 로컬 배포 자격증명으로 실제 BMA 세션을 생성해 새 Runtime의
get_account_context → list_ec2_instances 연결과 공개 text delta 306개를 확인했다.
이 검사는 BMA→배포 Runtime→MCP 호환성 검사이며, 현재 웹의 Converse 검증과 구분한다.
근거: [BMA 호환성 재검증](../artifacts/e2e/bma-streaming-compatibility.json).

## 역할과 데이터 처리 검증

- 배포된 Runtime의 `roleArn`과 CloudFormation RuntimeRole 출력이 일치했다.
- IAM 시뮬레이터에서 RuntimeRole의 서울 EC2 조회는 allowed,
  오레곤 EC2 조회와 StopInstances는 implicitDeny였다.
- WebRole과 SessionRole은 서울 EC2 조회 권한이 없었다.
- SessionRole에는 지정 글로벌 모델 스트리밍 권한이 있고, WebRole은 지정 SessionRole만 AssumeRole한다.
- 실제 MCP 결과의 STS 계정은 기대 계정과 일치했다.
- 실제 조회 결과에서 Lambda 환경 변수·자격증명 등 제외 필드가 없음을 확인했다.
- 5개 결과가 us-west-2 앱 버킷에 저장됐고 두 보고서 형식을 모두 다운로드했다.

근거: [역할 검증](../artifacts/deployed-streaming-proof.json),
[현재 활성 배포](../artifacts/ui-deployment-proof.json),
[현재 브라우저 검증](../artifacts/e2e-ui/summary.json).
서울 조회 정보 중 모델에 전달된 내용은 현재 글로벌 프로파일로 처리된다.
앱과 Runtime, 결과 저장은 us-west-2에 있다.

## 배포 중 확인하고 수정한 사항

1. **코드 버킷 서비스 권한:** Web Revision 생성에는 배포 주체의 권한 외에
   `lambda.amazonaws.com`의 `s3:GetObject`·`s3:GetObjectVersion` 권한이 필요했다.
   `web/` prefix와 지정 Web Function의 `revision/*` SourceArn으로 제한해 추가했다.
   첫 롤백에서 남은 빈 앱 버킷과 빈 Web 로그 그룹은 확인 후 정리했다.
2. **Web Revision 교체:** Web Revision은 불변 리소스이므로
   `DisableRollback=True`로는 교체 업데이트할 수 없었다.
   안정 상태로 복구한 뒤 일반 교체 업데이트로 반영했다.
3. **Runtime 설정 상속:** BMA 연결 설정에서 MCP의 계정·리전·한도는
   `env_vars`로 Runtime 환경에서 상속하고 `required=true`로 연결을 필수화했다.
4. **초기 기동:** 초기 Runtime 자격증명 준비·연결 지연이 실제로 발생했다.
   세션 생성 대기를 120초로 늘리고, 이벤트 스트림의 일시적 503에만 제한된 재시도를 추가했다.
   POST 세션 생성은 중복 작업을 피하기 위해 자동 재시도하지 않는다.

## 운영 및 재검증

```bash
.venv/bin/python scripts/verify_deployed.py --case inventory
.venv/bin/python scripts/verify_deployed.py --case ec2-health
.venv/bin/python scripts/verify_deployed.py --case ecs
.venv/bin/python scripts/verify_deployed.py --case lambda
.venv/bin/python scripts/verify_deployed.py --case alarms
.venv/bin/python scripts/verify_deployed_browser.py --language ko
.venv/bin/python scripts/verify_deployed_browser.py --language en
.venv/bin/python scripts/verify_deployed_browser.py --language ko --report-preview
.venv/bin/python scripts/verify_deployed_browser.py --language en --report-preview
.venv/bin/python scripts/verify_extended_deployed.py --case network
.venv/bin/python scripts/verify_extended_deployed.py --case configuration
.venv/bin/python scripts/verify_extended_deployed.py --case security
.venv/bin/python scripts/verify_extended_browser.py
```

이 명령은 실제 모델과 AWS API를 호출하므로 해당 비용이 발생할 수 있다.
서비스별 2개·단일 클러스터·Lambda 1개 제한을 유지한다.

앱 결과는 7일 보존한다. 이 배포가 생성한 Runtime 진단 로그에도 7일 보존을 적용했다.
BMA 경로의 세션과 앱 S3 파일은 별도 수명주기이며 성공한 BMA 세션을 자동 삭제하지 않는다.
현재 Converse 경로는 질문당 Runtime 세션을 사용하며 BMA 세션을 생성하지 않는다.
디버깅을 포함해 생성한 Runtime 세션은 idle timeout에 따라 종료된다.
공유 접속 키 방식은 신뢰된 사용자용 데모이며 사용자별 테넌트 격리는 제공하지 않는다.
