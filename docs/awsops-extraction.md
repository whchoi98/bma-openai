# 원본 AWSops 기능 추출

> 이 문서는 최초 설계 또는 오레곤 추출 검증 기록을 포함합니다. 현재 실행 리전과 모델은 [배포 보고서](aws-deployment.md)를 기준으로 확인합니다.

추출 원본은 사용자 확인에 따라 `/home/ec2-user/my-project/awsops`다.
앞서 검토한 `awsops_v2`를 구현 원본으로 사용하지 않았다.
원본 저장소의 서버, SQL 실행 경로, 인증 설정이나 배포 스크립트는 실행하거나 변경하지 않았다.

## 구현한 세 범위

1. **VPC, EBS, ECR 조회와 관계도**  
   소유 VPC와 보안 그룹을 검증하고, 서브넷/라우팅 테이블/게이트웨이/엔드포인트의 관측된 참조를 표시한다.
   EBS 연결도 양쪽 리소스가 실제로 조회됐을 때만 그린다. 관계도는 통신 시험 결과가 아니다.
2. **보고서 이력과 DOCX/PPTX**  
   계정과 대상 리전으로 구분한 S3 이력을 최신순으로 조회한다. 이력 로드와 문서 변환은 모델이나
   리소스를 다시 조회하지 않는다. 기존 Markdown/HTML과 같은 저장 근거를 사용한다.
3. **추가 인벤토리와 보안 구성 점검**  
   S3, DynamoDB, ElastiCache, OpenSearch, MSK의 구성 조회를 추가했다.
   보안 점검은 실제 구성 값의 pass/fail/unknown을 표시하며 전체 보안, 취약점, 앱 정상 판정으로 확대하지 않는다.

현재 지원 범위는 EC2, RDS, ECS, Lambda Event Functions, CloudWatch, VPC, EBS, ECR,
S3, DynamoDB, ElastiCache, OpenSearch, MSK의 13개 표시 범주다.
MCP는 24개 고정 도구를 제공한다. 지표 지원은 기존 EC2/RDS/ECS/Lambda 범위로 유지한다.

## 추출 출처

| 대상 | 원본에서 가져온 내용 | 현재 구현과 검증 |
| --- | --- | --- |
| 네트워크/EBS/ECR | network MCP와 VPC/EBS/ECR 조회 정의의 필드 및 관계 의미 | [extraction-network.md](extraction-network.md) |
| 추가 서비스 구성 | S3/DynamoDB/cache/search/MSK 조회 및 원본 MCP의 구성 읽기 | [extraction-config.md](extraction-config.md) |
| 문서와 이력 | report-docx/report-pptx의 파싱/레이아웃, 보고서 및 인벤토리 이력 개념 | [extraction-reports.md](extraction-reports.md) |
| 관계도 화면 | 원본 topology와 relationships의 참조 관계 | [extraction-ui.md](extraction-ui.md) |

각 문서에 원본 파일과 SHA-256을 기록했다. 원본의 범용 SQL, 임의 CLI, 자동 ECS 재시작,
가격 상수, 미조회 MFA 0 값, 사설 데이터 소스와 Kubernetes 내부 조회는 가져오지 않았다.

## 정확성과 한도

- 앱과 Runtime은 `us-west-2`, 리소스 조회는 `ap-northeast-2`다. Luna 모델 설정을 유지한다.
- STS 실행 계정 확인 외에, 공유될 수 있는 VPC와 보안 그룹은 실제 소유자도 검사한다.
- 도구당 리소스 상한, 페이지 상한, 최대 31 SDK 호출과 제한된 재시도를 적용한다.
  관계도의 종류별 완료/잘림/오류/미조회 상태를 보존한다.
- 보안 그룹 규칙은 최대 50개를 정규화한다. ICMPv6의 유효한 필드 생략과 잘못된 값을 구분한다.
- S3는 소유 서울 버킷 목록으로 상세 조회를 제한하고 ExpectedBucketOwner를 전달한다.
  객체, DynamoDB 항목, 캐시 내용, 검색 문서와 Kafka 메시지는 조회하지 않는다.
- 모든 보고서 형식은 서버에서 계정 번호를 가린다. 검증된 보고서 UUID는 이력 링크를 위해 유지한다.
  저장된 원본 JSON과 실제 계정 비교 값은 변경하지 않는다.

## 이력과 문서

앱 버킷의 `history/ACCOUNT/ap-northeast-2/` 아래에 역순 타임스탬프 인덱스를 저장한다.
페이지당 최대 20개, 화면은 최대 100개를 표시한다. 인덱스와 보고서는 7일 보관한다.
인덱스 쓰기만 실패하면 이미 저장한 보고서는 내려받을 수 있으며 실패 사실을 표시한다.
계정/리전/모드/버킷이 다른 페이지 커서는 거부한다.

기존 기록은 `node web/history-migrate.js --limit 200`으로 한 번에 최대 200개까지 인덱싱한다.
이 도구도 STS 계정을 먼저 확인하며 원본 보고서를 수정하거나 삭제하지 않는다.
범위를 증명할 수 없는 예전 기록은 건너뛰고 이유를 남긴다.

DOCX/PPTX 입력은 최대 1 MB, 출력은 최대 4 MB다. PPTX는 최대 40개 슬라이드이며
보이는 요약을 줄이면 그 사실을 표시하고 가려진 원문 근거를 발표자 노트에 보존한다.
두 포맷은 NanumSquare 글꼴을 지정한다. Office의 실제 표시 글꼴은 열람 환경의 설치 상태에 따른다.
HTML은 기존처럼 OTF 글꼴과 라이선스를 내장한다.

## 검증

로컬 회귀 검사, 계정/소유자/리전/페이지/권한 거부/빈 결과/부분 결과/민감 필드 검증,
문서 ZIP/XML 검사, 브라우저의 관계도/보안 표시/이력 로드/네 가지 다운로드를 수행한다.
실제 AWS 검증은 서비스별 소수 리소스와 현재 설정된 상한으로 실행하고,
조회되지 않은 서비스/리소스나 없는 설정을 만들어 채우지 않는다.
최종 배포와 관측 결과는 [배포 기록](aws-deployment.md)에 남긴다.

검증 완료: 로컬 345개 테스트, 실제 조회 세 흐름에서 AWS Request ID 42개,
계정별 이력 로드와 네 가지 보고서 다운로드를 확인했다.
추출 원본 파일 20개 해시가 유지됐다. 기존 보고서 28개 중 범위를 증명한 27개를 이력에 등록했고
확인할 수 없는 1개는 원본을 유지한 채 제외했다.
