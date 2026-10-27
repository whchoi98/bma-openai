---
name: aws-security-posture
description: 같은 계정의 서울 리전에서 보안 그룹, EBS, RDS, ECR, S3, DynamoDB 및 지원 데이터 서비스의 실제 구성 값을 조회하고 미확인 항목을 구분한다.
---

# AWS 보안 구성 점검

이 Skill은 조회 절차다. IAM 권한이나 도구의 입력 제한을 바꾸지 않는다.
`get_account_context()`로 실제 실행 계정과 서울 대상 리전을 먼저 확인한다.
계정 검증이 실패하면 조회를 중단한다.

사용자가 요청한 서비스만 점검한다.

- VPC 보안 그룹: `list_vpcs()`에서 소유가 확인된 VPC를 선택하고 `list_security_groups(vpc_id)`를 호출한다.
- EBS: `list_ebs_volumes()`의 암호화와 연결 정보를 확인한다. 미연결 상태만으로 삭제 대상이라고 판단하지 않는다.
- RDS: `list_rds_instances()`의 `storage_encrypted`, `publicly_accessible`와 `security_checks`를 확인한다.
- ECR: `list_ecr_repositories()`의 암호화, 태그 변경 정책과 저장소의 scan-on-push 설정을 확인한다.
  scan-on-push 값만으로 모든 이미지 스캔이 켜졌거나 꺼졌다고 판단하지 않는다.
- S3: `list_s3_buckets()` 후 반환된 이름으로 `get_s3_bucket_configuration(bucket)`를 호출한다.
  공개 접근 차단, 버킷 정책의 공개 여부, 암호화와 버전 관리는 별도 관측이다.
  계정 수준 정책이나 다른 접근 경로까지 검사한 것으로 확대하지 않는다.
- DynamoDB: 목록 후 `get_dynamodb_table_configuration(table_name)`으로 구성과 PITR를 확인한다.
- ElastiCache: 반환된 암호화 값만 사용한다. AUTH 토큰 필드가 없다고 인증이 없다고 단정하지 않는다.
- OpenSearch: 목록 후 `get_opensearch_domain_configuration(domain_name)`을 호출한다.
- MSK: `list_msk_clusters()`에 실제로 포함된 암호화와 인증 구성만 사용한다.

`security_checks`의 pass, fail, unknown을 구분한다.
pass는 해당 구성 기준을 충족했다는 뜻이며 전체 보안 정상이나 애플리케이션 정상의 증거가 아니다.
fail도 취약점 악용이나 장애가 발생했다는 확정 판정이 아니다.
unknown, 권한 부족, 누락된 필드, 일부 페이지만 조회한 결과를 pass로 바꾸지 않는다.
조회되지 않은 리소스에는 결과를 확장하지 않는다. 전체 CIS 점수나 인증 결과를 만들지 않는다.

계정, 리전, 도구와 API, 원본 관측 시각, 조회 범위와 잘림을 표시한다.
보안 그룹의 구성 관계도는 통신 시험 결과가 아니다.
추가 지표는 기존 EC2/RDS/ECS/Lambda 허용 범위만 사용한다.
SQL, 객체 본문, 테이블 항목, 캐시 명령, 검색 문서, Kafka 메시지, 로그 검색과 변경 API는 실행하지 않는다.

한국어 또는 영어 선택을 따른다. us-east-1의 한국어 지명은 버지니아 북부로 표기한다.
과장과 반복을 줄이고 문장 구분에 가운뎃점, 엠대시, 이모지를 쓰지 않는다.
리소스 ID와 ARN은 원문을 인라인 코드로 표시한다.
