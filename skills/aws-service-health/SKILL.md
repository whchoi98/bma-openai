---
name: aws-service-health
description: 서울 리전 AWS 서비스의 구성 상태, 상태 점검, 제한된 CloudWatch 지표와 알람을 확인하고 관측 사실과 진단 가설을 구분한다.
---

# AWS 서비스 상태 확인

처음에 `get_account_context()`를 호출한다. STS 실패나 계정 불일치이면 중단한다.
이 지침은 IAM 권한을 부여하지 않는다. 실제 조회는 등록된 MCP 도구로만 수행한다.

요청한 서비스의 목록에서 실제 반환된 ID를 선택한다. 질문에 없는 서비스를 일괄 조회하지 않는다.

| 서비스 | 구성 및 상태 점검 | 관련 지표 식별자 |
| --- | --- | --- |
| EC2 | `list_ec2_instances`, 반환 ID를 최대 20개씩 `get_ec2_instance_health` | EC2 인스턴스 ID |
| RDS | `list_rds_instances`의 인스턴스 상태 | DBInstanceIdentifier |
| ECS | `list_ecs_clusters`, `list_ecs_services`, 서비스 최대 10개씩 `get_ecs_service_health` | `클러스터명/서비스명` |
| Lambda Event Functions | `list_lambda_functions`, 구성 상태가 필요하면 `get_lambda_function_health` | 함수 이름 |

ECS는 목표, 실행, 대기 태스크 수와 배포의 rollout state를 읽는다. 태스크 수의 차이가
일시적 배포인지 장애인지 단정하지 않는다. ListFunctions는 State를 보장하지 않으므로
목록만 보고 Lambda가 Active라고 쓰지 않는다.

관련 지표는 `get_resource_metrics(service, resource_id, start_time, end_time)`로 조회한다.
시간에는 반드시 UTC `Z` 또는 명시적 오프셋을 넣는다. 기본 질문 “최근 한 시간”은
도구의 현재 UTC 관측 시각을 끝으로 잡고 한 시간 전을 시작으로 한다.
도구 한도는 기간 최대 6시간, 최근 7일 이내, 300초 버킷, 최대 1,440개 데이터 포인트이다.
첫 조회에서는 최대 5개 리소스만 선택하고 나머지는 미조회로 표시한다.

- EC2: CPUUtilization, StatusCheckFailed.
- RDS: CPUUtilization, DatabaseConnections, FreeableMemory.
- ECS: CPUUtilization, MemoryUtilization.
- Lambda: Invocations, Errors, Throttles, Duration.

필요하면 `list_cloudwatch_alarms("ALARM")`를 조회한다. 이것은 서울의 ALARM 목록이다.
이름이 비슷하다는 이유만으로 특정 리소스의 관련 알람이라고 단정하지 않는다.
복합 알람의 종속 관계, 지표 수학과 사용자 정의 지표는 이 데모에서 분석하지 않는다.

답변은 다음 순서로 작성한다.

1. **관측 사실:** 계정, 리전, 리소스 ID, API, UTC 시각/기간과 반환 상태, 수치.
2. **조회 한계:** 빈 목록, 접근 거부, API 실패, 부분 페이지, 누락 ID, 지표 없음.
3. **진단 가설:** 가설임을 표시하고 지지하는 사실, 반대 가능성, 추가 확인을 함께 쓴다.
   근거가 부족하면 가설을 억지로 만들지 않는다.
4. **추가 확인:** 이 도구에서 실행하지 않은 애플리케이션 점검과 권한, 기간 확인.

데이터 없음은 0이나 정상으로 바꾸지 않는다. PartialData/Forbidden/오류를 완전한
관측으로 쓰지 않는다. `running`, `available`, `Active`, 정상 상태 점검, 알람 없음 중
어느 하나만으로 애플리케이션 정상 또는 장애를 판정하지 않는다.
DB SQL, 사설 HTTP, Kubernetes API, 로그 검색, 수정, 중지, 재시작은 수행하지 않는다.

화면에서 선택한 한국어 또는 영어로 짧고 자연스럽게 작성한다. 상투적인 도입과 반복적인 결론을 생략한다.
문장 구분에 엠대시, 가운뎃점, 이모지를 쓰지 않는다. 리소스 ID와 ARN은 원문을 인라인 코드로 표시한다.

추가 구성 조회 도구는 VPC, EBS, ECR, S3, DynamoDB, ElastiCache, OpenSearch, MSK를 지원한다.
VPC 관계도는 `list_vpcs` 후 `get_vpc_topology(vpc_id)`로 확인하고 관측된 구성 관계만 설명한다.
S3/DynamoDB/OpenSearch는 목록에서 이름을 얻은 뒤 해당 configuration 도구로 상태를 확인한다.
보안 설정 요청에는 `aws-security-posture` 절차를 따른다. 지표 지원 범위는 EC2/RDS/ECS/Lambda로 한정한다.
