# 서비스별 API·IAM 대응표

확인일: 2026-10-26. boto3/botocore **1.43.118**의 서비스 모델과 아래 공식 SDK 문서,
AWS의 [기계 판독용 서비스 권한 정보](https://servicereference.us-east-1.amazonaws.com/)를 대조했다.
실제 정책은 [infra/template.yaml](../infra/template.yaml)의 RuntimeRole에 있다.

모든 도구는 먼저 `sts:GetCallerIdentity`로 같은 자격증명 체인의 실제 계정을 확인한다.
기대 계정이 다르거나 확인할 수 없으면 해당 리소스 조회를 실행하지 않는다.
STS 자체는 별도 권한이 없어도 호출할 수 있는 작업이며, 명시 정책은 글로벌 식별 확인 항목으로 분리했다.

2026-10-27 추가된 원본 `awsops` 추출 도구를 포함해 MCP 도구는 24개다.
각 도구는 STS를 포함해 최대 31회의 실제 SDK 호출을 허용하며, 상한에서는 부분 조회를 표시한다.

| MCP 도구 | boto3 클라이언트 / SDK 작업 | IAM Action | 리소스 범위·페이지네이션 |
| --- | --- | --- | --- |
| `get_account_context()` | `sts.get_caller_identity` / [GetCallerIdentity](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/sts/client/get_caller_identity.html) | `sts:GetCallerIdentity` | `*`; us-east-1 STS 엔드포인트, 비페이지 작업 |
| `list_ec2_instances()` | `ec2.describe_instances` / [DescribeInstances](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_instances.html) | `ec2:DescribeInstances` | `*`; Reservations 안 Instances를 평탄화, NextToken |
| `get_ec2_instance_health(instance_ids)` | `ec2.describe_instance_status` / [DescribeInstanceStatus](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2/client/describe_instance_status.html) | `ec2:DescribeInstanceStatus` | `*`; 최대 20 ID, IncludeAllInstances=true, NextToken |
| `list_rds_instances()` | `rds.describe_db_instances` / [DescribeDBInstances](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/rds/client/describe_db_instances.html) | `rds:DescribeDBInstances` | `arn:aws:rds:ap-northeast-2:ACCOUNT:db:*`; Marker |
| `list_ecs_clusters()` | `ecs.list_clusters` / [ListClusters](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ecs/client/list_clusters.html) | `ecs:ListClusters` | `*`; nextToken |
| `list_ecs_services(cluster)` | `ecs.list_services` / [ListServices](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ecs/client/list_services.html) | `ecs:ListServices` | `*`; 지정 클러스터, nextToken |
| `get_ecs_service_health(cluster, services)` | `ecs.describe_services` / [DescribeServices](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ecs/client/describe_services.html) | `ecs:DescribeServices` | `arn:aws:ecs:ap-northeast-2:ACCOUNT:service/*`; 최대 10개, 비페이지 작업; failures 별도 처리 |
| `list_lambda_functions()` | `lambda.list_functions` / [ListFunctions](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/lambda/client/list_functions.html) | `lambda:ListFunctions` | `*`; Marker/NextMarker; Event Functions의 기본 버전 목록 |
| `get_lambda_function_health(function_name)` | `lambda.get_function_configuration` / [GetFunctionConfiguration](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/lambda/client/get_function_configuration.html) | `lambda:GetFunctionConfiguration` | `arn:aws:lambda:ap-northeast-2:ACCOUNT:function:*`; 1개, State·LastUpdateStatus 허용 목록 |
| `get_resource_metrics(service, resource_id, start_time, end_time)` | `cloudwatch.get_metric_data` / [GetMetricData](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cloudwatch/client/get_metric_data.html) | `cloudwatch:GetMetricData` | `*`; 고정 AWS namespace/dimensions/statistics, NextToken |
| `list_cloudwatch_alarms(state)` | `cloudwatch.describe_alarms` / [DescribeAlarms](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cloudwatch/client/describe_alarms.html) | `cloudwatch:DescribeAlarms` | `*`; MetricAlarm + CompositeAlarm, NextToken |

`ACCOUNT`는 실제 CloudFormation 배포 계정이다. 위 지역 서비스 정책에는
`StringEquals: {aws:RequestedRegion: ap-northeast-2}`가 적용된다.
도구 인자로 계정·리전·임의 SDK operation을 받지 않는다.

## 원본 awsops에서 추출한 추가 조회

| MCP 도구 | SDK API | IAM 액션 | 제한 |
| --- | --- | --- | --- |
| `list_vpcs` | EC2 DescribeVpcs | ec2:DescribeVpcs | owner-id 필터와 응답 OwnerId 검증 |
| `get_vpc_topology(vpc_id)` | DescribeVpcs, DescribeSubnets, DescribeRouteTables, DescribeSecurityGroups, DescribeInternetGateways, DescribeNatGateways, DescribeVpcEndpoints | 각 API의 ec2 동명 액션 | 소유 VPC 확인 후 호출, 도구 전체 행 상한, 종류별 완료/잘림/미조회 표시 |
| `list_security_groups(vpc_id)` | DescribeSecurityGroups | ec2:DescribeSecurityGroups | vpc-id와 owner-id 필터, 응답 소유자 검증, ingress 최대 50개 |
| `list_ebs_volumes` | DescribeVolumes | ec2:DescribeVolumes | 연결 ID와 암호화 등 허용 필드만 |
| `list_ecr_repositories` | DescribeRepositories | ecr:DescribeRepositories | 서울의 같은 계정 repository ARN으로 제한 |
| `list_s3_buckets` | ListBuckets | s3:ListAllMyBuckets | 서울 BucketRegion, 페이지/리소스 제한 |
| `get_s3_bucket_configuration(bucket)` | ListBuckets, GetBucketEncryption, GetPublicAccessBlock, GetBucketPolicyStatus, GetBucketVersioning | s3:ListAllMyBuckets, s3:GetEncryptionConfiguration, s3:GetBucketPublicAccessBlock, s3:GetBucketPolicyStatus, s3:GetBucketVersioning | 소유 서울 버킷 목록에서 정확한 이름 확인 후 ExpectedBucketOwner 적용 |
| `list_dynamodb_tables` | ListTables | dynamodb:ListTables | 이름만 조회, 항목 데이터 없음 |
| `get_dynamodb_table_configuration(table_name)` | DescribeTable, DescribeContinuousBackups | dynamodb:DescribeTable, dynamodb:DescribeContinuousBackups | 서울의 같은 계정 table ARN |
| `list_elasticache_clusters` | DescribeCacheClusters | elasticache:DescribeCacheClusters | 서울의 같은 계정 cluster ARN, 엔드포인트와 캐시 내용 제외 |
| `list_opensearch_domains` | ListDomainNames | es:ListDomainNames | 이름만 조회, 초과 목록 잘림 표시 |
| `get_opensearch_domain_configuration(domain_name)` | DescribeDomain | es:DescribeDomain | 서울의 같은 계정 domain ARN, 정책/엔드포인트/문서 제외 |
| `list_msk_clusters` | Kafka ListClustersV2 | kafka:ListClustersV2 | 클러스터 구성만, 메시지/토픽/브로커 접속 주소 제외 |

EC2 Describe 계열과 DynamoDB/OpenSearch/MSK의 위 목록 액션은 리소스 수준 권한을 제공하지 않아
`Resource="*"`를 사용한다. ECR, DynamoDB 상세, ElastiCache, OpenSearch 상세는 해당 리전과 계정의
리소스 ARN 패턴으로 제한한다. S3 버킷 상세는 `s3:ResourceAccount=ACCOUNT`도 적용한다.
서울 요청 리전 조건은 조회 정책에만 적용하며, ECR 이미지 pull이나 앱의 버지니아 북부 S3 저장 정책과 분리한다.

공식 SDK 문서와 AWS 기계 판독 권한 자료로 검증한 상세 근거:
[네트워크 API/IAM 및 원본 해시](extraction-network.md),
[추가 구성 API/IAM 및 원본 해시](extraction-config.md).
SDK의 MSK 클라이언트 이름은 `kafka`, 도구의 서비스 표시는 `msk`다.

이력에는 WebRole의 S3 `ListBucket` 권한을 추가한다. 대상은 앱 버킷 하나와
`history/ACCOUNT/ap-northeast-2/` prefix로 제한한다. 인덱스 Get/Put도 같은 prefix만 허용한다.
Runtime에는 앱 결과 파일이나 이력 인덱스 접근 권한을 부여하지 않는다.
DOCX/PPTX 변환은 이미 저장한 기록으로 수행하며 새 AWS 리소스 조회 권한을 사용하지 않는다.

## Resource="*"가 필요한 이유

- EC2 DescribeInstances/DescribeInstanceStatus, ECS ListClusters/ListServices, Lambda ListFunctions는
  해당 작업의 리소스 수준 권한을 지원하지 않는다. 서비스별 계정 목록을 반환하는 동작이다.
- 표준 AWS namespace의 GetMetricData에는 특정 인스턴스나 함수 ARN을 IAM Resource로 지정할 수 없다.
  새 CloudWatch dataset 리소스 권한과 이 데모의 AWS 서비스 지표 조회는 다른 범위이다.
- DescribeAlarms는 metric alarm ARN으로 좁힐 수 있는 경우가 있지만, **composite alarm 반환에는
  `Resource="*"`가 필요**하므로 두 유형을 함께 지원하는 이 도구는 지역 조건을 붙인 `*`를 사용한다.
- STS GetCallerIdentity는 리소스 수준 권한 대상이 아니다.

확인한 공식 IAM 사양:
[EC2](https://servicereference.us-east-1.amazonaws.com/v1/ec2/ec2.json),
[RDS](https://servicereference.us-east-1.amazonaws.com/v1/rds/rds.json),
[ECS](https://servicereference.us-east-1.amazonaws.com/v1/ecs/ecs.json),
[Lambda](https://servicereference.us-east-1.amazonaws.com/v1/lambda/lambda.json),
[CloudWatch](https://servicereference.us-east-1.amazonaws.com/v1/cloudwatch/cloudwatch.json).

## Lambda의 두 목록 API

`boto3.client("lambda").list_functions()`는 **Event Functions** 목록이다.
[Lambda API 문서](https://docs.aws.amazon.com/lambda/latest/api/API_ListFunctions.html)도 이를 명시한다.
이 응답은 State·LastUpdateStatus를 보장하지 않아 목록에서는 해당 상태를 `null`로 표시한다.
필요할 때만 별도 GetFunctionConfiguration을 호출한다.

Web Functions는 **다른 클라이언트**
[`boto3.client("lambda-web").list_web_functions()`](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/lambda-web/client/list_web_functions.html)와
`lambda:ListWebFunctions`를 사용한다. 이번 MCP에는 이 도구·IAM 권한을 부여하지 않는다.
배포 과정에서 Web Function을 생성하는 관리 권한과 조회 도구 권한을 혼동하지 않는다.

[공식 Web Functions 런타임 문서](https://docs.aws.amazon.com/lambda/latest/dg/web-functions-runtimes.html)에 따라
배포 웹 앱은 `nodejs24.x`를 사용한다.

## 지표 범위

| 서비스 | Namespace / dimensions | Metric / statistic |
| --- | --- | --- |
| EC2 | AWS/EC2 / InstanceId | CPUUtilization Average, StatusCheckFailed Maximum |
| RDS | AWS/RDS / DBInstanceIdentifier | CPUUtilization Average, DatabaseConnections Average, FreeableMemory Average |
| ECS | AWS/ECS / ClusterName + ServiceName | CPUUtilization Average, MemoryUtilization Average |
| Lambda Event Functions | AWS/Lambda / FunctionName | Invocations Sum, Errors Sum, Throttles Sum, Duration Average |

기간 최대 6시간, 최근 7일 이내, 300초 버킷, 최대 1,440개 데이터 포인트이다.
Metric math, Metrics Insights, 로그 쿼리, 교차 계정 AccountId, 사용자 지정 namespace를 받지 않는다.
PartialData/Forbidden/InternalError/누락 시리즈를 구분한다. 모든 시리즈 실패는 `api_error`,
일부 실패는 `partial`, 성공한 빈 시리즈는 `no_data`이다.

## BMA와 실행 인프라 정책

| 역할 | 정책 책임 |
| --- | --- |
| WebRole | BMA CreateAgentSession/CreateAgentSessionEvent/ListAgentSessionEvents/ListAgentSessionItems, 지정 SessionRole PassRole/AssumeRole, 앱 결과 S3 Get/Put, 지정 로그 그룹 쓰기 |
| SessionRole | BMA `openai.gpt-6-luna`의 CreateInference, 지정 Runtime 및 DEFAULT endpoint InvokeAgentRuntime/StopRuntimeSession |
| RuntimeRole | BMA RegisterEnvironment/ConnectEnvironment, 지정 ECR 이미지 pull, Runtime 로그, 글로벌 STS 확인, 위 서울 조회 목록 |

BMA 세션 역할의 trust principal은 `bedrock-mantle.amazonaws.com`이며 SourceAccount/SourceArn으로 제한한다.
Converse 경로에서는 같은 계정의 해당 스택 WebRole만 SessionRole을 AssumeRole할 수 있다.
trust의 계정 principal에 `aws:PrincipalArn=arn:aws:iam::ACCOUNT:role/STACK-WebRole-*` 조건을 붙여
CloudFormation 순환 의존성을 피하고, WebRole 권한은 실제 SessionRole ARN 하나로 제한했다.
Runtime 역할은 `bedrock-agentcore.amazonaws.com`, Web 역할은 `lambda.amazonaws.com`을 신뢰한다.
CreateInference는 모델 ARN 대신 `Resource="*"`와 `bedrock-mantle:Model` 조건을 사용한다.
ECR GetAuthorizationToken도 `*`가 필요하며 조회 정책과 분리했다.
앱의 S3 저장·BMA 호출에 서울 RequestedRegion 조건을 적용하지 않는다.

Web Function 코드 버킷에는 별도의 서비스 주체 정책이 필요하다.
`lambda.amazonaws.com`에 `web/` prefix의 `s3:GetObject`, `s3:GetObjectVersion`만 허용하고
`aws:SourceArn`을 지정 함수의 `web-function/함수명/revision/*`로 제한한다.
근거: [Lambda Web Functions S3 코드 정책](https://docs.aws.amazon.com/lambda/latest/dg/web-functions-code-s3.html).

별도 조회 역할 AssumeRole은 기본 구현에 없다. 필요해지면 고정한 단일 역할 ARN만 허용하고,
assume 이후 새 자격증명으로 STS 검증을 다시 수행해야 한다. 질문에서 역할 ARN을 받아서는 안 된다.
Converse용 SessionRole AssumeRole은 모델·Runtime 호출 책임을 유지하기 위한 것이며,
서울 리소스 조회 권한을 WebRole이나 SessionRole에 부여하지 않는다.

### 선택 가능한 Converse 스트리밍 API와 권한

현재 BMA 배포에는 아래 글로벌 추론 정책이 없다. `AgentBackend=converse`일 때만
CloudFormation의 `UseConverse` 조건으로 부여한다. 아래 ARN은 2026-10-26 오레곤 검증 기록이다.

| SDK 작업 | IAM Action | 허용 범위 |
| --- | --- | --- |
| STS `AssumeRoleCommand` | `sts:AssumeRole` | WebRole에서 지정 SessionRole ARN만 |
| Bedrock Runtime `ConverseStreamCommand` | `bedrock:InvokeModelWithResponseStream` | `global.openai.gpt-6-luna` 프로파일 ARN과 GetInferenceProfile이 반환한 모델 ARN만 |
| AgentCore `InvokeAgentRuntimeCommand` | `bedrock-agentcore:InvokeAgentRuntime` | 지정 Runtime 및 DEFAULT endpoint |

2026-10-26 GetInferenceProfile로 확인한 허용 리소스는 다음 세 개다.

```text
arn:aws:bedrock:us-west-2:ACCOUNT:inference-profile/global.openai.gpt-6-luna
arn:aws:bedrock:::foundation-model/openai.gpt-6-luna
arn:aws:bedrock:us-west-2::foundation-model/openai.gpt-6-luna
```

이 모델 추론 정책에는 서울 RequestedRegion 조건을 붙이지 않는다. 임의 모델 ARN도 허용하지 않는다.
공식 API 기준:
[ConverseStream](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_ConverseStream.html),
[InvokeAgentRuntime](https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_InvokeAgentRuntime.html),
[AssumeRole](https://docs.aws.amazon.com/STS/latest/APIReference/API_AssumeRole.html).

BMA 역할·MCP·스트림 기준:
[Security and IAM roles](https://docs.aws.amazon.com/bedrock/latest/userguide/bedrock-managed-agents-openai-security.html),
[Skills and tools](https://docs.aws.amazon.com/bedrock/latest/userguide/bedrock-managed-agents-openai-skills-tools.html),
[Runtime guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-bma.html).
최신 Runtime 예제에 맞춰 이벤트 경로에 `?stream=true`를 넣고 **그 쿼리를 포함하여 SigV4 서명**한다.
실제 배포에서는 MCP를 `required=true`로 지정하고, 계정·리전·한도·자격증명 환경 변수는
이름만 `env_vars`에 명시하여 Runtime에서 상속한다. 값이나 자격증명을 세션 요청에 복사하지 않는다.


## 운영 조사 worker와 상태 복구

WorkerRole을 추가했다. BMA `CreateAgentSession`, `GetAgentSession`, `ListAgentSessions`,
`CreateAgentSessionEvent`, `ListAgentSessionEvents`, `ListAgentSessionItems`를 같은 계정의
us-east-1 project ARN에만 허용한다. `iam:PassRole`은 기존 SessionRole 한 개와
`iam:PassedToService=bedrock-mantle.amazonaws.com`으로 제한한다.
WebRole은 지정 worker의 `lambda:InvokeFunction`만 추가하며 새 BMA Get 권한은 필요하지 않다.
WorkerRole에는 EC2/RDS 등 리소스 조회나 직접 모델 추론, Runtime 호출 권한이 없다.

앱 상태 Get/Put은 `investigations/ACCOUNT/ap-northeast-2/`로 제한한다.
조사 목록 ListBucket은 그 아래 `index/`만 허용한다. S3 객체 부재와 권한 오류를 구분하는
추가 ListObjectsV2는 검증된 UUID의 전체 객체 키에 `MaxKeys=1`로 호출하며, IAM의 키 패턴과
`NumericLessThanEquals: {s3:max-keys: 1}` 조건을 함께 적용한다.
403을 빈 결과로 바꾸지 않으며 부재를 입증할 수 없으면 원래 오류를 유지한다.

현재 worker와 웹 역할에 대한 [실제 권한 검증 12개](../artifacts/investigations/iam-live.json)가 통과했다.
공식 근거: [BMA 보안 및 IAM](https://docs.aws.amazon.com/bedrock/latest/userguide/bedrock-managed-agents-openai-security.html),
[GetObject 오류 구분](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html),
[S3 조건부 쓰기](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html),
[Lambda Invoke](https://docs.aws.amazon.com/lambda/latest/api/API_Invoke.html).
