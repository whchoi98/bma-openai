"""Synthetic, deterministic SDK responses for configuration inventory."""

from botocore.exceptions import ClientError

from .config import SAMPLE_ACCOUNT

REGION = "ap-northeast-2"
BUCKET = "sample-inventory-config"
TABLE = "sample-orders"
DOMAIN = "sample-search"
MSK_ARN = f"arn:aws:kafka:{REGION}:{SAMPLE_ACCOUNT}:cluster/sample-stream/00000000-0000-0000-0000-000000000001-1"


def _not_found(operation):
    raise ClientError(
        {"Error": {"Code": "ResourceNotFoundException", "Message": "Synthetic resource is not present."}},
        operation,
    )


def response(service, operation, params):
    """Return a new boto-style value, or KeyError for an unowned operation."""
    key = (service, operation)
    if key == ("s3", "list_buckets"):
        available = params.get("BucketRegion") == REGION and BUCKET.startswith(params.get("Prefix", ""))
        return {"Buckets": [{"Name": BUCKET, "BucketRegion": REGION}] if available else []}
    if key in {
        ("s3", "get_bucket_encryption"), ("s3", "get_public_access_block"),
        ("s3", "get_bucket_policy_status"), ("s3", "get_bucket_versioning"),
    }:
        if params.get("Bucket") != BUCKET or params.get("ExpectedBucketOwner") != SAMPLE_ACCOUNT:
            raise ClientError(
                {"Error": {"Code": "AccessDenied", "Message": "Synthetic owner or bucket mismatch."}},
                operation,
            )
        if operation == "get_bucket_encryption":
            return {"ServerSideEncryptionConfiguration": {"Rules": [
                {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
            ]}}
        if operation == "get_public_access_block":
            return {"PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True, "IgnorePublicAcls": True,
                "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
            }}
        if operation == "get_bucket_policy_status":
            return {"PolicyStatus": {"IsPublic": False}}
        return {"Status": "Enabled"}
    if key == ("dynamodb", "list_tables"):
        return {"TableNames": [TABLE]}
    if key in {("dynamodb", "describe_table"), ("dynamodb", "describe_continuous_backups")}:
        if params.get("TableName") != TABLE:
            _not_found(operation)
        if operation == "describe_table":
            return {"Table": {
                "TableName": TABLE,
                "TableArn": f"arn:aws:dynamodb:{REGION}:{SAMPLE_ACCOUNT}:table/{TABLE}",
                "TableStatus": "ACTIVE",
                "BillingModeSummary": {"BillingMode": "PAY_PER_REQUEST"},
                "SSEDescription": {"Status": "ENABLED"},
                "DeletionProtectionEnabled": True,
                "ItemCount": 12,
                "TableSizeBytes": 4096,
            }}
        return {"ContinuousBackupsDescription": {
            "ContinuousBackupsStatus": "ENABLED",
            "PointInTimeRecoveryDescription": {"PointInTimeRecoveryStatus": "DISABLED"},
        }}
    if key == ("elasticache", "describe_cache_clusters"):
        return {"CacheClusters": [{
            "CacheClusterId": "sample-cache",
            "ARN": f"arn:aws:elasticache:{REGION}:{SAMPLE_ACCOUNT}:cluster:sample-cache",
            "Engine": "valkey",
            "EngineVersion": "8.2",
            "CacheClusterStatus": "available",
            "CacheNodeType": "cache.t4g.small",
            "NumCacheNodes": 1,
            "AtRestEncryptionEnabled": True,
            "TransitEncryptionEnabled": True,
            "AuthTokenEnabled": False,
        }]}
    if key == ("opensearch", "list_domain_names"):
        return {"DomainNames": [{"DomainName": DOMAIN, "EngineType": "OpenSearch"}]}
    if key == ("opensearch", "describe_domain"):
        if params.get("DomainName") != DOMAIN:
            _not_found(operation)
        return {"DomainStatus": {
            "DomainId": f"{SAMPLE_ACCOUNT}/{DOMAIN}",
            "DomainName": DOMAIN,
            "ARN": f"arn:aws:es:{REGION}:{SAMPLE_ACCOUNT}:domain/{DOMAIN}",
            "EngineVersion": "OpenSearch_2.19",
            "Created": True,
            "Processing": False,
            "ClusterConfig": {"InstanceType": "t3.small.search", "InstanceCount": 1},
            "EncryptionAtRestOptions": {"Enabled": True},
            "NodeToNodeEncryptionOptions": {"Enabled": True},
            "DomainEndpointOptions": {"EnforceHTTPS": True},
            "AdvancedSecurityOptions": {"Enabled": True},
        }}
    if key == ("kafka", "list_clusters_v2"):
        return {"ClusterInfoList": [{
            "ClusterName": "sample-stream",
            "ClusterArn": MSK_ARN,
            "ClusterType": "PROVISIONED",
            "State": "ACTIVE",
            "Provisioned": {
                "BrokerNodeGroupInfo": {
                    "ClientSubnets": ["subnet-00000000000000001", "subnet-00000000000000002"],
                    "InstanceType": "kafka.t3.small",
                },
                "NumberOfBrokerNodes": 2,
                "CurrentBrokerSoftwareInfo": {"KafkaVersion": "3.8.x"},
                "EncryptionInfo": {
                    "EncryptionAtRest": {"DataVolumeKMSKeyId": "sample-key"},
                    "EncryptionInTransit": {"ClientBroker": "TLS", "InCluster": True},
                },
                "ClientAuthentication": {
                    "Sasl": {"Iam": {"Enabled": True}},
                    "Unauthenticated": {"Enabled": False},
                },
            },
        }]}
    raise KeyError(key)
