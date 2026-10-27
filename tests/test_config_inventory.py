"""Configuration inventory exercises real SDK models without making AWS requests."""

import json
from datetime import datetime, timezone

import pytest
from conftest import ACCOUNT, NOW

from aws_inventory.config import Settings
from aws_inventory.engine import AwsInventory

REGION = "ap-northeast-2"
BUCKET = "sample-inventory-config"
TABLE = "sample-orders"
DOMAIN = "sample-search"
MSK_ARN = f"arn:aws:kafka:{REGION}:{ACCOUNT}:cluster/sample-stream/00000000-0000-0000-0000-000000000001-1"
S3_LIST = {"BucketRegion": REGION, "MaxBuckets": 100}
S3_GATE = {**S3_LIST, "Prefix": BUCKET}
S3_DETAIL = {"Bucket": BUCKET, "ExpectedBucketOwner": ACCOUNT}


def new_inventory(aws, **settings):
    aws.identity()
    return AwsInventory(
        Settings(expected_account_id=ACCOUNT, **settings), session=aws, clock=lambda: NOW
    )


def checks(row):
    return {check["id"]: check["status"] for check in row["security_checks"]}


def bucket_gate(aws, **extra):
    aws.stub("s3").add_response(
        "list_buckets",
        {"Buckets": [{"Name": BUCKET, "BucketRegion": REGION}], **extra},
        S3_GATE,
    )


def bucket_config(aws, *, public=True):
    stub = aws.stub("s3")
    stub.add_response(
        "get_bucket_encryption",
        {"ServerSideEncryptionConfiguration": {"Rules": [
            {"ApplyServerSideEncryptionByDefault": {
                "SSEAlgorithm": "aws:kms",
                "KMSMasterKeyID": "sensitive-kms-key",
            }}
        ]}},
        S3_DETAIL,
    )
    stub.add_response(
        "get_public_access_block",
        {"PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": not public,
            "RestrictPublicBuckets": True,
        }},
        S3_DETAIL,
    )
    stub.add_response(
        "get_bucket_policy_status", {"PolicyStatus": {"IsPublic": public}}, S3_DETAIL
    )
    stub.add_response("get_bucket_versioning", {"Status": "Enabled"}, S3_DETAIL)


def table_description(**overrides):
    return {"Table": {
        "TableName": TABLE,
        "TableArn": f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{TABLE}",
        "TableStatus": "ACTIVE",
        "BillingModeSummary": {"BillingMode": "PAY_PER_REQUEST"},
        "SSEDescription": {"Status": "ENABLED", "KMSMasterKeyArn": "sensitive-kms-key"},
        "KeySchema": [{"AttributeName": "sensitive-schema-name", "KeyType": "HASH"}],
        "DeletionProtectionEnabled": True,
        **overrides,
    }}


def domain_description(**overrides):
    return {"DomainStatus": {
        "DomainId": f"{ACCOUNT}/{DOMAIN}",
        "DomainName": DOMAIN,
        "ARN": f"arn:aws:es:{REGION}:{ACCOUNT}:domain/{DOMAIN}",
        "EngineVersion": "OpenSearch_2.19",
        "ClusterConfig": {"InstanceType": "t3.small.search", "InstanceCount": 2},
        "Endpoint": "sensitive-endpoint.example",
        "AccessPolicies": '{"sensitive-policy": true}',
        "AdvancedOptions": {"sensitive-option": "secret"},
        "EncryptionAtRestOptions": {"Enabled": True, "KmsKeyId": "sensitive-kms-key"},
        "NodeToNodeEncryptionOptions": {"Enabled": False},
        "DomainEndpointOptions": {"EnforceHTTPS": True, "CustomEndpoint": "sensitive-custom.example"},
        "AdvancedSecurityOptions": {"Enabled": True},
        **overrides,
    }}


def msk_cluster(**overrides):
    return {
        "ClusterName": "sample-stream",
        "ClusterArn": MSK_ARN,
        "ClusterType": "PROVISIONED",
        "State": "ACTIVE",
        "Tags": {"sensitive-tag": "secret"},
        "Provisioned": {
            "BrokerNodeGroupInfo": {
                "ClientSubnets": ["subnet-00000000000000001"],
                "InstanceType": "kafka.t3.small",
            },
            "NumberOfBrokerNodes": 2,
            "CurrentBrokerSoftwareInfo": {"KafkaVersion": "3.8.x"},
            "EncryptionInfo": {
                "EncryptionAtRest": {"DataVolumeKMSKeyId": "sensitive-kms-key"},
                "EncryptionInTransit": {"ClientBroker": "TLS_PLAINTEXT", "InCluster": True},
            },
            "ClientAuthentication": {
                "Unauthenticated": {"Enabled": False},
                "Sasl": {"Iam": {"Enabled": True}},
            },
            "ZookeeperConnectString": "sensitive-zookeeper.example:2181",
        },
        **overrides,
    }


def test_s3_discovery_uses_regional_owner_list_and_strips_owner_details(aws, inventory):
    aws.stub("s3").add_response(
        "list_buckets",
        {
            "Buckets": [{
                "Name": BUCKET,
                "BucketRegion": REGION,
                "CreationDate": datetime(2026, 1, 1, tzinfo=timezone.utc),
            }],
            "Owner": {"DisplayName": "sensitive-owner", "ID": "sensitive-canonical-id"},
        },
        S3_LIST,
    )
    result = inventory.invoke("list_s3_buckets")
    assert result["status"] == "ok"
    assert result["pagination_complete"]
    assert result["data"][0]["id"] == BUCKET
    assert result["data"][0]["region"] == REGION
    assert "sensitive-" not in json.dumps(result)
    assert {region for name, region in aws.regions if name != "sts"} == {REGION}
    assert [call["api"] for call in result["api_calls"]] == ["GetCallerIdentity", "ListBuckets"]


def test_s3_discovery_paginates_with_region_filter(aws, inventory):
    aws.stub("s3").add_response(
        "list_buckets", {"Buckets": [], "ContinuationToken": "page-two"}, S3_LIST
    )
    aws.stub("s3").add_response(
        "list_buckets", {"Buckets": [{"Name": BUCKET, "BucketRegion": REGION}]},
        {**S3_LIST, "ContinuationToken": "page-two"},
    )
    result = inventory.invoke("list_s3_buckets")
    assert result["status"] == "ok"
    assert result["pagination_complete"]
    assert result["count"] == 1


def test_s3_detail_is_gated_and_all_bucket_calls_bind_owner(aws, inventory):
    bucket_gate(aws)
    bucket_config(aws)
    result = inventory.invoke("get_s3_bucket_configuration", {"bucket": BUCKET})
    assert result["status"] == "ok"
    assert result["count"] == 1
    row = result["data"][0]
    assert row["encryption_algorithms"] == ["aws:kms"]
    assert row["versioning_status"] == "Enabled"
    assert checks(row) == {
        "s3_encryption_enabled": "pass",
        "s3_bucket_public_access_block": "fail",
        "s3_bucket_policy_not_public": "fail",
        "s3_versioning_enabled": "pass",
    }
    assert "sensitive-" not in json.dumps(result)
    assert len(result["api_calls"]) == 6
    aws.stub("s3").assert_no_pending_responses()


@pytest.mark.parametrize("listed", [
    [],
    [{"Name": BUCKET, "BucketRegion": "us-east-1"}],
    [{"Name": BUCKET}],
    [{"Name": BUCKET + "-suffix", "BucketRegion": REGION}],
])
def test_s3_detail_never_calls_bucket_api_without_exact_regional_membership(aws, inventory, listed):
    aws.stub("s3").add_response("list_buckets", {"Buckets": listed}, S3_GATE)
    result = inventory.invoke("get_s3_bucket_configuration", {"bucket": BUCKET})
    assert result["data"] == []
    assert result["status"] != "ok"
    assert [call["api"] for call in result["api_calls"]] == ["GetCallerIdentity", "ListBuckets"]


def test_s3_denied_encryption_stays_unknown_and_other_reads_are_preserved(aws, inventory):
    bucket_gate(aws)
    aws.stub("s3").add_client_error(
        "get_bucket_encryption", "AccessDenied", expected_params=S3_DETAIL
    )
    aws.stub("s3").add_response(
        "get_public_access_block", {"PublicAccessBlockConfiguration": {}}, S3_DETAIL
    )
    aws.stub("s3").add_response("get_bucket_policy_status", {}, S3_DETAIL)
    aws.stub("s3").add_response("get_bucket_versioning", {"Status": "Suspended"}, S3_DETAIL)
    result = inventory.invoke("get_s3_bucket_configuration", {"bucket": BUCKET})
    assert result["status"] == "partial"
    assert result["permission_denied"]
    assert checks(result["data"][0]) == {
        "s3_encryption_enabled": "unknown",
        "s3_bucket_public_access_block": "unknown",
        "s3_bucket_policy_not_public": "unknown",
        "s3_versioning_enabled": "fail",
    }


def test_s3_scope_gate_is_bounded_by_max_pages(aws):
    inv = new_inventory(aws, max_pages=2)
    for token, request in [("one", S3_GATE), ("two", {**S3_GATE, "ContinuationToken": "one"})]:
        aws.stub("s3").add_response(
            "list_buckets", {"Buckets": [], "ContinuationToken": token}, request
        )
    result = inv.invoke("get_s3_bucket_configuration", {"bucket": BUCKET})
    assert result["truncated"]
    assert not result["pagination_complete"]
    assert result["count"] == 0
    assert len(result["api_calls"]) == 3


def test_dynamodb_discovery_is_ids_only_and_paginates(aws, inventory):
    aws.stub("dynamodb").add_response(
        "list_tables", {"TableNames": ["sample-first"], "LastEvaluatedTableName": "sample-first"},
        {"Limit": 100},
    )
    aws.stub("dynamodb").add_response(
        "list_tables", {"TableNames": [TABLE]}, {"Limit": 100, "ExclusiveStartTableName": "sample-first"},
    )
    result = inventory.invoke("list_dynamodb_tables")
    assert result["resource_ids"] == ["sample-first", TABLE]
    assert result["pagination_complete"]
    assert all("security_checks" not in row for row in result["data"])
    assert [call["api"] for call in result["api_calls"]] == [
        "GetCallerIdentity", "ListTables", "ListTables",
    ]


def test_dynamodb_detail_uses_control_plane_pitr_and_sanitizes_response(aws, inventory):
    aws.stub("dynamodb").add_response("describe_table", table_description(), {"TableName": TABLE})
    aws.stub("dynamodb").add_response(
        "describe_continuous_backups",
        {"ContinuousBackupsDescription": {
            "ContinuousBackupsStatus": "ENABLED",
            "PointInTimeRecoveryDescription": {"PointInTimeRecoveryStatus": "DISABLED"},
        }},
        {"TableName": TABLE},
    )
    result = inventory.invoke("get_dynamodb_table_configuration", {"table_name": TABLE})
    assert result["status"] == "ok"
    assert result["data"][0]["billing_mode"] == "PAY_PER_REQUEST"
    assert checks(result["data"][0]) == {
        "dynamodb_encryption_enabled": "pass",
        "dynamodb_point_in_time_recovery": "fail",
    }
    assert "sensitive-" not in json.dumps(result)
    assert len(result["api_calls"]) == 3


def test_dynamodb_absent_encryption_and_denied_backups_remain_unknown(aws, inventory):
    aws.stub("dynamodb").add_response(
        "describe_table", table_description(SSEDescription={}), {"TableName": TABLE}
    )
    aws.stub("dynamodb").add_client_error(
        "describe_continuous_backups", "AccessDeniedException", expected_params={"TableName": TABLE}
    )
    result = inventory.invoke("get_dynamodb_table_configuration", {"table_name": TABLE})
    assert result["status"] == "partial"
    assert set(checks(result["data"][0]).values()) == {"unknown"}


@pytest.mark.parametrize("bad_arn", [
    f"arn:aws:dynamodb:us-east-1:{ACCOUNT}:table/{TABLE}",
    f"arn:aws:dynamodb:{REGION}:999999999999:table/{TABLE}",
])
def test_dynamodb_rejects_response_outside_verified_scope(aws, inventory, bad_arn):
    aws.stub("dynamodb").add_response(
        "describe_table", table_description(TableArn=bad_arn), {"TableName": TABLE}
    )
    result = inventory.invoke("get_dynamodb_table_configuration", {"table_name": TABLE})
    assert result["data"] == []
    assert result["errors"][0]["code"] == "ResourceOutsideScope"
    assert len(result["api_calls"]) == 2


def test_elasticache_paginates_without_node_endpoints_and_preserves_observed_flags(aws, inventory):
    params = {"MaxRecords": 100, "ShowCacheNodeInfo": False}
    aws.stub("elasticache").add_response(
        "describe_cache_clusters", {"CacheClusters": [], "Marker": "next"}, params
    )
    aws.stub("elasticache").add_response(
        "describe_cache_clusters",
        {"CacheClusters": [{
            "CacheClusterId": "sample-cache",
            "ARN": f"arn:aws:elasticache:{REGION}:{ACCOUNT}:cluster:sample-cache",
            "Engine": "valkey",
            "EngineVersion": "8.2",
            "CacheClusterStatus": "available",
            "NumCacheNodes": 1,
            "AtRestEncryptionEnabled": True,
            "TransitEncryptionEnabled": False,
            "AuthTokenEnabled": False,
            "ConfigurationEndpoint": {"Address": "sensitive-endpoint.example", "Port": 6379},
            "CacheNodes": [{"CacheNodeId": "0001", "Endpoint": {"Address": "sensitive-node", "Port": 6379}}],
        }]},
        {**params, "Marker": "next"},
    )
    result = inventory.invoke("list_elasticache_clusters")
    assert result["pagination_complete"]
    row = result["data"][0]
    assert row["auth_token_enabled"] is False
    assert checks(row) == {
        "elasticache_encryption_at_rest": "pass",
        "elasticache_encryption_in_transit": "fail",
    }
    assert "sensitive-" not in json.dumps(result)


def test_opensearch_discovery_is_bounded_without_implicit_details(aws):
    inv = new_inventory(aws, max_resources=1)
    aws.stub("opensearch").add_response(
        "list_domain_names", {"DomainNames": [
            {"DomainName": DOMAIN, "EngineType": "OpenSearch"},
            {"DomainName": "sample-second", "EngineType": "Elasticsearch"},
        ]}, {},
    )
    result = inv.invoke("list_opensearch_domains")
    assert result["count"] == 1
    assert result["truncated"]
    assert not result["pagination_complete"]
    assert len(result["api_calls"]) == 2


def test_opensearch_detail_removes_endpoint_policies_and_nested_options(aws, inventory):
    aws.stub("opensearch").add_response(
        "describe_domain", domain_description(), {"DomainName": DOMAIN}
    )
    result = inventory.invoke("get_opensearch_domain_configuration", {"domain_name": DOMAIN})
    assert result["status"] == "ok"
    assert checks(result["data"][0]) == {
        "opensearch_encryption_at_rest": "pass",
        "opensearch_node_to_node_encryption": "fail",
        "opensearch_https_required": "pass",
        "opensearch_advanced_security_enabled": "pass",
    }
    assert "sensitive-" not in json.dumps(result)


def test_opensearch_missing_configuration_is_unknown(aws, inventory):
    aws.stub("opensearch").add_response(
        "describe_domain",
        domain_description(
            EncryptionAtRestOptions={}, NodeToNodeEncryptionOptions={},
            DomainEndpointOptions={}, AdvancedSecurityOptions={},
        ),
        {"DomainName": DOMAIN},
    )
    result = inventory.invoke("get_opensearch_domain_configuration", {"domain_name": DOMAIN})
    assert set(checks(result["data"][0]).values()) == {"unknown"}


def test_msk_uses_kafka_sdk_and_separate_msk_evidence_name(aws, inventory):
    aws.stub("kafka").add_response(
        "list_clusters_v2", {"ClusterInfoList": [msk_cluster()]}, {"MaxResults": 100}
    )
    result = inventory.invoke("list_msk_clusters")
    assert result["status"] == "ok"
    assert result["service"] == "msk"
    assert result["api_calls"][-1]["service"] == "msk"
    assert ("kafka", REGION) in aws.regions
    assert checks(result["data"][0]) == {
        "msk_encryption_at_rest": "pass",
        "msk_client_tls_only": "fail",
        "msk_in_cluster_encryption": "pass",
        "msk_unauthenticated_access_disabled": "pass",
    }
    assert "sensitive-" not in json.dumps(result)


def test_msk_serverless_missing_flags_are_unknown(aws, inventory):
    cluster = msk_cluster(ClusterType="SERVERLESS")
    del cluster["Provisioned"]
    cluster["Serverless"] = {
        "VpcConfigs": [{"SubnetIds": ["subnet-00000000000000001"]}],
        "ClientAuthentication": {"Sasl": {"Iam": {"Enabled": True}}},
    }
    aws.stub("kafka").add_response(
        "list_clusters_v2", {"ClusterInfoList": [cluster]}, {"MaxResults": 100}
    )
    result = inventory.invoke("list_msk_clusters")
    assert set(checks(result["data"][0]).values()) == {"unknown"}
    assert result["data"][0]["iam_authentication_enabled"] is True
    assert result["data"][0]["broker_count"] is None


@pytest.mark.parametrize(("tool", "service", "operation", "params", "empty"), [
    ("list_s3_buckets", "s3", "list_buckets", S3_LIST, {"Buckets": []}),
    ("list_dynamodb_tables", "dynamodb", "list_tables", {"Limit": 100}, {"TableNames": []}),
    ("list_elasticache_clusters", "elasticache", "describe_cache_clusters",
     {"MaxRecords": 100, "ShowCacheNodeInfo": False}, {"CacheClusters": []}),
    ("list_opensearch_domains", "opensearch", "list_domain_names", {}, {"DomainNames": []}),
    ("list_msk_clusters", "kafka", "list_clusters_v2", {"MaxResults": 100}, {"ClusterInfoList": []}),
])
def test_empty_discovery_is_complete_without_invented_security_passes(
    aws, inventory, tool, service, operation, params, empty
):
    aws.stub(service).add_response(operation, empty, params)
    result = inventory.invoke(tool)
    assert result["status"] == "empty"
    assert result["pagination_complete"]
    assert result["data"] == []


@pytest.mark.parametrize(("tool", "args"), [
    ("get_s3_bucket_configuration", {"bucket": "arn:aws:s3:::foreign-bucket"}),
    ("get_s3_bucket_configuration", {"bucket": "s3://sample-bucket"}),
    ("get_s3_bucket_configuration", {"bucket": "192.0.2.1"}),
    ("get_s3_bucket_configuration", {"bucket": "sample-bucket--x-s3"}),
    ("get_dynamodb_table_configuration", {
        "table_name": f"arn:aws:dynamodb:{REGION}:999999999999:table/{TABLE}",
    }),
    ("get_opensearch_domain_configuration", {
        "domain_name": f"arn:aws:es:{REGION}:{ACCOUNT}:domain/{DOMAIN}",
    }),
    ("list_s3_buckets", {"region": "us-east-1"}),
    ("list_msk_clusters", {"operation": "get_bootstrap_brokers"}),
    ("get_dynamodb_table_configuration", {"table_name": 123}),
])
def test_inputs_cannot_select_other_scope_or_arbitrary_operations(inventory, tool, args):
    result = inventory.invoke(tool, args)
    assert result["status"] == "invalid_input"
    assert [call["api"] for call in result["api_calls"]] == ["GetCallerIdentity"]


def test_account_mismatch_stops_before_any_configuration_service(aws):
    aws.identity(account="999999999999")
    inv = AwsInventory(Settings(expected_account_id=ACCOUNT), session=aws)
    result = inv.invoke("list_msk_clusters")
    assert result["status"] == "account_mismatch"
    assert len(result["api_calls"]) == 1


@pytest.mark.parametrize(("tool", "service", "operation", "params", "response"), [
    ("list_s3_buckets", "s3", "list_buckets",
     {"BucketRegion": REGION, "MaxBuckets": 1},
     {"Buckets": [{"Name": BUCKET, "BucketRegion": REGION}], "ContinuationToken": "next"}),
    ("list_dynamodb_tables", "dynamodb", "list_tables", {"Limit": 1},
     {"TableNames": [TABLE], "LastEvaluatedTableName": TABLE}),
    ("list_elasticache_clusters", "elasticache", "describe_cache_clusters",
     {"MaxRecords": 20, "ShowCacheNodeInfo": False},
     {"CacheClusters": [{"CacheClusterId": "sample-cache"}], "Marker": "next"}),
    ("list_msk_clusters", "kafka", "list_clusters_v2", {"MaxResults": 1},
     {"ClusterInfoList": [msk_cluster()], "NextToken": "next"}),
])
def test_resource_limit_stops_pagination(aws, tool, service, operation, params, response):
    inv = new_inventory(aws, max_resources=1)
    aws.stub(service).add_response(operation, response, params)
    result = inv.invoke(tool)
    assert result["count"] == 1
    assert result["truncated"]
    assert not result["pagination_complete"]
    assert len(result["api_calls"]) == 2


def test_discovery_access_denial_is_not_an_empty_inventory(aws, inventory):
    aws.stub("opensearch").add_client_error(
        "list_domain_names", "AccessDeniedException", expected_params={}
    )
    result = inventory.invoke("list_opensearch_domains")
    assert result["status"] == "access_denied"
    assert result["permission_denied"]
    assert not result["pagination_complete"]


def test_repeated_msk_pagination_token_reports_partial_evidence(aws, inventory):
    for params in [{"MaxResults": 100}, {"MaxResults": 100, "NextToken": "same"}]:
        aws.stub("kafka").add_response(
            "list_clusters_v2", {"ClusterInfoList": [], "NextToken": "same"}, params
        )
    result = inventory.invoke("list_msk_clusters")
    assert result["errors"][0]["code"] == "RepeatedPaginationToken"
    assert not result["pagination_complete"]
    assert len(result["api_calls"]) == 3


@pytest.mark.parametrize(("tool", "args"), [
    ("list_s3_buckets", {}),
    ("get_s3_bucket_configuration", {"bucket": BUCKET}),
    ("list_dynamodb_tables", {}),
    ("get_dynamodb_table_configuration", {"table_name": TABLE}),
    ("list_elasticache_clusters", {}),
    ("list_opensearch_domains", {}),
    ("get_opensearch_domain_configuration", {"domain_name": DOMAIN}),
    ("list_msk_clusters", {}),
])
def test_fixed_sample_adapter_exercises_every_tool_and_respects_sdk_models(tool, args):
    from botocore.session import Session
    from botocore.validate import validate_parameters

    from aws_inventory.config import SAMPLE_ACCOUNT
    from aws_inventory.config_samples import response

    models = Session()

    class Client:
        def __init__(self, service):
            self.service = service

        def __getattr__(self, operation):
            def call(**params):
                if self.service == "sts":
                    return {"Account": SAMPLE_ACCOUNT}
                result = response(self.service, operation, params)
                service_model = models.get_service_model(self.service)
                api = next(
                    api for api in service_model.operation_names
                    if re_snake(api) == operation
                )
                operation_model = service_model.operation_model(api)
                validate_parameters(params, operation_model.input_shape)
                validate_parameters(result, operation_model.output_shape)
                return result
            return call

    class AdapterSession:
        def client(self, service, *, region_name, config=None):
            assert region_name == ("us-east-1" if service == "sts" else REGION)
            return Client(service)

    inv = AwsInventory(
        Settings(expected_account_id=SAMPLE_ACCOUNT, mode="sample"), session=AdapterSession()
    )
    result = inv.invoke(tool, args)
    assert result["status"] == "ok"
    assert 0 < result["count"] <= 100
    assert len(result["api_calls"]) <= 31
    for row in result["data"]:
        for check in row.get("security_checks", []):
            assert set(check) == {"id", "status", "severity"}
            assert check["status"] in {"pass", "fail", "unknown"}
            assert check["severity"] in {"high", "medium", "info"}


def re_snake(api):
    from botocore import xform_name

    return xform_name(api)


def test_sample_adapter_does_not_claim_unowned_or_data_plane_operations():
    from aws_inventory.config_samples import response

    for service, operation in [
        ("ec2", "describe_instances"),
        ("s3", "get_object"),
        ("dynamodb", "scan"),
        ("dynamodb", "query"),
        ("kafka", "get_bootstrap_brokers"),
        ("opensearch", "update_domain_config"),
    ]:
        with pytest.raises(KeyError):
            response(service, operation, {})


def test_s3_detail_can_find_exact_bucket_on_a_later_page(aws, inventory):
    aws.stub("s3").add_response(
        "list_buckets", {"Buckets": [], "ContinuationToken": "later"}, S3_GATE
    )
    aws.stub("s3").add_response(
        "list_buckets", {"Buckets": [{"Name": BUCKET, "BucketRegion": REGION}]},
        {**S3_GATE, "ContinuationToken": "later"},
    )
    bucket_config(aws)
    result = inventory.invoke("get_s3_bucket_configuration", {"bucket": BUCKET})
    assert result["status"] == "ok"
    assert result["count"] == 1
    assert len(result["api_calls"]) == 7


def test_s3_scope_gate_rejects_a_repeated_token(aws, inventory):
    for params in [S3_GATE, {**S3_GATE, "ContinuationToken": "same"}]:
        aws.stub("s3").add_response(
            "list_buckets", {"Buckets": [], "ContinuationToken": "same"}, params
        )
    result = inventory.invoke("get_s3_bucket_configuration", {"bucket": BUCKET})
    assert result["errors"][0]["code"] == "RepeatedPaginationToken"
    assert result["data"] == []
    assert len(result["api_calls"]) == 3


@pytest.mark.parametrize("tool", [
    "get_dynamodb_table_configuration", "get_opensearch_domain_configuration",
])
def test_configuration_description_for_a_sibling_resource_is_rejected(aws, inventory, tool):
    if tool.startswith("get_dynamodb"):
        args = {"table_name": TABLE}
        aws.stub("dynamodb").add_response(
            "describe_table",
            table_description(TableArn=f"arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/{TABLE}-sibling"),
            {"TableName": TABLE},
        )
    else:
        args = {"domain_name": DOMAIN}
        aws.stub("opensearch").add_response(
            "describe_domain",
            domain_description(ARN=f"arn:aws:es:{REGION}:{ACCOUNT}:domain/{DOMAIN}-sibling"),
            {"DomainName": DOMAIN},
        )
    result = inventory.invoke(tool, args)
    assert result["data"] == []
    assert result["errors"][0]["code"] == "ResourceOutsideScope"
