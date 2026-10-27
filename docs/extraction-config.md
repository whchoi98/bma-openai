# AWSops configuration inventory extraction

> 이 문서는 최초 설계 또는 오레곤 추출 검증 기록을 포함합니다. 현재 실행 리전과 모델은 [배포 보고서](aws-deployment.md)를 기준으로 확인합니다.

Implemented on 2026-10-27 from `/home/ec2-user/my-project/awsops`. The source repository was read as text; its servers, Lambda handlers, scripts, SQL, and AWS clients were not executed. This extraction does not use `awsops_v2`.

## Provenance

SHA-256 values identify the original files inspected:

| Original file under `awsops/` | SHA-256 | Adaptation |
| --- | --- | --- |
| `agent/lambda/aws_dynamodb_mcp.py` | `38b9641d937ebe030a3a9d56898b36b11b620e9b7d09608ad832748bdee04181` | Table discovery and configuration fields. Removed list-to-describe fan-out, item reads, query/scan, capacity-price guidance, caller-selected accounts and Regions. |
| `agent/lambda/aws_valkey_mcp.py` | `30a0427d475e795dd5fc2fd3dc873041e89267d5e034f9935dfaf4f641293b80` | Provisioned cache-cluster identity, engine, state and node configuration. Disabled cache-node detail retrieval; omitted all connection endpoints, replication-group and serverless expansions. |
| `agent/lambda/aws_msk_mcp.py` | `ccd7fb0c2956e7fcc93628d7192160dd2b8e6c05fe3bead693f00e60854c823c` | `ListClustersV2` and its provisioned/serverless structure. Removed bootstrap-broker, ZooKeeper, node and configuration-content APIs. |
| `src/lib/queries/s3.ts` | `516d3cb465d7954547022bb1e5a94b64c30ed8bab3a9becf8d052749412b7829` | Bucket configuration concepts: encryption, public-access flags and versioning. Uses explicit SDK calls, without SQL, tags, policy documents, logging targets or lifecycle rules. |
| `src/lib/queries/dynamodb.ts` | `6cabd7b17d1a9a905640a1650194f741641be70356cb83c8eaa873ffc3f5f747` | Observed table state, billing, encryption and PITR. Uses a separate named-table detail tool and `DescribeContinuousBackups`. |
| `src/lib/queries/elasticache.ts` | `3c30d2e4ff4750bdfe386a8ecb58bdc86c2dd5004b546417607109058e6e4277` | Encryption and AUTH-token flags. No cache contents, node addresses, metrics, tags or automatic related-resource queries. |
| `src/lib/queries/opensearch.ts` | `9973a8f455f53ce2b9279e543044dddd1e48f4708a03ca6f3d0cb5d830309648` | Separate domain discovery/detail, engine configuration and observed encryption/security flags. Omitted endpoints, policies, advanced options, identity configuration and tags. |
| `src/lib/queries/msk.ts` | `4e36d1eb8030ba0ae7a214b386637125001538f1f587e9f389ee1d3a4b85b5d6` | Nested provisioned cluster fields and encryption observations. No tags, bootstrap strings, broker configuration contents or Kafka data. |
| `src/lib/queries/security.ts` | `c984335e2bc949a99fe2d7f7097bbec546363f115e2109d91127f0d4d602af9e` | Configuration-finding concepts only. No IAM-user enumeration, vulnerability ingestion, SQL execution or synthesized compliance results. |

## Registration and scope

`aws_inventory/config_inventory.py` exports `TOOL_SCHEMAS`, `DATA_FIELDS`, and `handlers(engine)`. It owns strict Pydantic argument classes with `extra="forbid"`. It does not import the shared schema or engine at module initialization; `QueryStopped` is imported only inside the independent-read helper.

The shared engine verifies `EXPECTED_ACCOUNT_ID` through STS before every invocation. Every service client is created by the shared engine in `ap-northeast-2`. The STS client uses the fixed application Region, `us-west-2`. Inputs accept only a bucket, table, or domain name where required. ARN, endpoint, account, Region and arbitrary-operation inputs are not supported. Returned resource ARNs, when present, must match the configured account, Region, service and resource identity before the resource is emitted.

S3 needs an additional ownership and location gate. `ListBuckets` is called at the Seoul endpoint with `BucketRegion="ap-northeast-2"` and an explicit `MaxBuckets`. The API returns buckets owned by the authenticated caller. Each returned bucket must also report the Seoul `BucketRegion`. The detail tool adds `Prefix=bucket` and accepts only an exact name match before issuing any bucket request. A prefix match, missing Region, different Region, exhausted pages, or denied listing cannot authorize a detail call. This avoids `HeadBucket`, `GetBucketLocation`, redirects for arbitrary bucket names, and requests against buckets outside Seoul. Directory buckets, access-point aliases and multi-Region access points are excluded.

## API and IAM matrix

The installed Boto3 and Botocore versions were both `1.43.118`. Their real service models were used by Stubber. The official latest Boto3 pages resolved to version `1.43.119` on 2026-10-27; the required parameters and response fields agree with the installed model. No SDK upgrade was required.

| Tool | Exact API / Python method | IAM action | IAM resource scope |
| --- | --- | --- | --- |
| `list_s3_buckets`; S3 detail gate | [ListBuckets / `list_buckets`](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/list_buckets.html) | `s3:ListAllMyBuckets` | `*` |
| `get_s3_bucket_configuration` | [GetBucketEncryption / `get_bucket_encryption`](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/get_bucket_encryption.html) | `s3:GetEncryptionConfiguration` | `arn:aws:s3:::*` |
| same | [GetPublicAccessBlock / `get_public_access_block`](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/get_public_access_block.html) | `s3:GetBucketPublicAccessBlock` | `arn:aws:s3:::*` |
| same | [GetBucketPolicyStatus / `get_bucket_policy_status`](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/get_bucket_policy_status.html) | `s3:GetBucketPolicyStatus` | `arn:aws:s3:::*` |
| same | [GetBucketVersioning / `get_bucket_versioning`](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/get_bucket_versioning.html) | `s3:GetBucketVersioning` | `arn:aws:s3:::*` |
| `list_dynamodb_tables` | [ListTables / `list_tables`](https://docs.aws.amazon.com/boto3/latest/reference/services/dynamodb/client/list_tables.html) | `dynamodb:ListTables` | `*` |
| `get_dynamodb_table_configuration` | [DescribeTable / `describe_table`](https://docs.aws.amazon.com/boto3/latest/reference/services/dynamodb/client/describe_table.html) | `dynamodb:DescribeTable` | `arn:aws:dynamodb:ap-northeast-2:<account>:table/*` |
| same | [DescribeContinuousBackups / `describe_continuous_backups`](https://docs.aws.amazon.com/boto3/latest/reference/services/dynamodb/client/describe_continuous_backups.html) | `dynamodb:DescribeContinuousBackups` | same table scope |
| `list_elasticache_clusters` | [DescribeCacheClusters / `describe_cache_clusters`](https://docs.aws.amazon.com/boto3/latest/reference/services/elasticache/client/describe_cache_clusters.html) | `elasticache:DescribeCacheClusters` | `arn:aws:elasticache:ap-northeast-2:<account>:cluster:*` |
| `list_opensearch_domains` | [ListDomainNames / `list_domain_names`](https://docs.aws.amazon.com/boto3/latest/reference/services/opensearch/client/list_domain_names.html) | `es:ListDomainNames` | `*` |
| `get_opensearch_domain_configuration` | [DescribeDomain / `describe_domain`](https://docs.aws.amazon.com/boto3/latest/reference/services/opensearch/client/describe_domain.html) | `es:DescribeDomain` | `arn:aws:es:ap-northeast-2:<account>:domain/*` |
| `list_msk_clusters` | [ListClustersV2 / `list_clusters_v2`](https://docs.aws.amazon.com/boto3/latest/reference/services/kafka/client/list_clusters_v2.html) | `kafka:ListClustersV2` | `*` |

The Service Authorization Reference HTML service pages redirected to their index during verification. The action names, resource types and read-only properties above were instead verified against AWS's official, machine-readable authorization reference:

- [S3 authorization reference](https://servicereference.us-east-1.amazonaws.com/v1/s3/s3.json)
- [DynamoDB authorization reference](https://servicereference.us-east-1.amazonaws.com/v1/dynamodb/dynamodb.json)
- [ElastiCache authorization reference](https://servicereference.us-east-1.amazonaws.com/v1/elasticache/elasticache.json)
- [OpenSearch authorization reference](https://servicereference.us-east-1.amazonaws.com/v1/es/es.json)
- [MSK authorization reference](https://servicereference.us-east-1.amazonaws.com/v1/kafka/kafka.json)

S3 bucket-level actions support `s3:ResourceAccount`; the Runtime IAM statement should require the configured account. All four bucket requests also set `ExpectedBucketOwner` to that account. The list action has no resource ARN restriction. Use Seoul `aws:RequestedRegion` restrictions on compatible service-read statements; the S3 listing explicitly uses the matching regional endpoint required by the documented `BucketRegion` parameter.

`GetBucketPolicyStatus` contributes only `PolicyStatus.IsPublic`; the tool does not call `GetBucketPolicy`. No object, item, scan, query, cache, Kafka topic/message, search-index, credential, environment, write or deletion permissions are required by this module. The MSK SDK client is named `kafka`, while tool/evidence display service is `msk`.

## Bounds and observations

Let `P = max_pages`, constrained by shared settings to at most 10. Every tool returns at most `max_resources` rows, constrained to 1–100.

| Tool | Maximum API entries including STS | Result behavior |
| --- | --- | --- |
| S3 list | `1 + P`, at most 11 | Bucket identities only; regional pagination. |
| S3 detail | `1 + P + 4`, at most 15 | One bucket; bounded discovery gate followed by four independent configuration reads. |
| DynamoDB list | `1 + P`, at most 11 | Table identities only. |
| DynamoDB detail | 3 | One table plus observed PITR configuration. |
| ElastiCache list | `1 + P`, at most 11 | Provisioned cache configuration; `ShowCacheNodeInfo=False`. |
| OpenSearch list | 2 | API has no pagination parameters; excess returned names are truncated explicitly. |
| OpenSearch detail | 2 | One managed domain's allowlisted configuration. |
| MSK list | `1 + P`, at most 11 | Provisioned/serverless cluster configuration from the list response. |

Repeated continuation tokens are errors. Page or resource exhaustion records truncation and incomplete pagination. Denied listing calls remain errors, not empty inventories. Detail calls keep successful independent evidence while recording failures; `pagination_complete` does not erase those errors. Shared SDK timeouts, bounded retries and call metadata remain in effect.

Every security check has exactly `id`, `status` (`pass`, `fail`, `unknown`) and `severity` (`high`, `medium`, `info`). Missing configuration and failed reads remain unknown. Identity-only lists do not fabricate security checks.

- S3 checks separately describe default encryption, all four bucket public-access blocks, whether the observed bucket policy is public, and versioning. They do not determine effective public accessibility; account blocks, ACLs and access points are not queried. Missing versioning status remains unknown. KMS references are discarded.
- DynamoDB checks use returned SSE status and returned PITR status. Missing SSE configuration is not replaced with an assumption based on the service's default encryption behavior. Aggregate table size/count metadata does not expose items or key schema.
- ElastiCache checks use returned at-rest and in-transit flags. `AuthTokenEnabled=False` is reported as a flag but is not classified as absent authentication because RBAC is not queried.
- OpenSearch checks use returned at-rest encryption, node-to-node encryption, HTTPS enforcement and advanced-security flags. Missing VPC information is not interpreted as public access. Endpoints and policy contents are discarded.
- MSK encryption checks use observed configuration only. A returned encryption key reference establishes the at-rest flag, but the reference is discarded. `TLS_PLAINTEXT` permits plaintext and does not pass the TLS-only check. Absent provisioned encryption flags on serverless responses remain unknown. Authentication mechanisms are reported only when their flags are present.

These are configuration observations. They do not establish application health, test connectivity, certify compliance or prove that every access path is protected.

## Sample integration and verification

`aws_inventory/config_samples.py` exports `response(service, operation, params)`, where service is the SDK service name and operation is the snake-case SDK method. It returns fresh synthetic responses, raises `KeyError` for operations it does not own, and does not create AWS clients. Synthetic names are `sample-inventory-config`, `sample-orders`, `sample-cache`, `sample-search` and `sample-stream`. It uses only the synthetic sample account `000000000000`.

`tests/test_config_inventory.py` uses real Botocore models and Stubber; no live AWS reads are made. Tests cover all 12 operations, every tool's sample execution, owner/Region gates, out-of-scope response ARNs, exact resource identity, malformed/extra arguments, pagination, repeated tokens, row/page bounds, empty lists, partial/denied reads, unknown security states, and removal of endpoints, policies, tags, key references and schema details.

Validation command for a read-only sandbox:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest --capture=sys -p no:cacheprovider tests/test_config_inventory.py
.venv/bin/ruff check --no-cache aws_inventory/config_inventory.py aws_inventory/config_samples.py tests/test_config_inventory.py
```

Shared integration still owns schema/handler registration, SDK-service registration, sample-session delegation, output allowlists, Runtime IAM, service-selection instructions, UI and full regression/deployment validation.
