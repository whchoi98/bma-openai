"""Bounded, configuration-only reads for five additional AWS services.

The engine verifies STS identity before dispatch. No caller can select a Region,
SDK operation, endpoint, role, query expression, or data-plane request.
"""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .normalize import timestamp


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class BucketArgs(Arguments):
    bucket: Annotated[
        str, Field(min_length=3, max_length=63, pattern=r"^[a-z0-9][a-z0-9.-]*[a-z0-9]$")
    ]

    @field_validator("bucket")
    @classmethod
    def general_purpose_bucket(cls, value):
        if (
            ".." in value
            or re.fullmatch(r"\d+\.\d+\.\d+\.\d+", value)
            or value.startswith(("xn--", "sthree-", "amzn-s3-demo-"))
            or value.endswith(("-s3alias", "--ol-s3", ".mrap", "--x-s3", "--table-s3"))
        ):
            raise ValueError("A general-purpose bucket name is required.")
        return value


class TableArgs(Arguments):
    table_name: Annotated[
        str, Field(min_length=3, max_length=255, pattern=r"^[A-Za-z0-9_.-]+$")
    ]


class DomainArgs(Arguments):
    domain_name: Annotated[
        str, Field(min_length=3, max_length=28, pattern=r"^[a-z][a-z0-9-]+$")
    ]


TOOL_SCHEMAS = {
    "list_s3_buckets": (
        "s3", Arguments,
        "List bounded, owned general-purpose S3 buckets in Seoul; no objects or configuration fan-out.",
    ),
    "get_s3_bucket_configuration": (
        "s3", BucketArgs,
        "Verify one owned Seoul bucket, then read encryption, public-access flags, and versioning.",
    ),
    "list_dynamodb_tables": (
        "dynamodb", Arguments, "List bounded DynamoDB table names in Seoul; no table items or implicit details.",
    ),
    "get_dynamodb_table_configuration": (
        "dynamodb", TableArgs, "Read one Seoul table's configuration and point-in-time recovery; no items.",
    ),
    "list_elasticache_clusters": (
        "elasticache", Arguments,
        "List bounded provisioned cache-cluster configuration; excludes endpoints, cache contents, and serverless.",
    ),
    "list_opensearch_domains": (
        "opensearch", Arguments, "List bounded managed domain names in Seoul; no indices or implicit details.",
    ),
    "get_opensearch_domain_configuration": (
        "opensearch", DomainArgs, "Read one managed domain's configuration flags; no endpoint, policy, or indices.",
    ),
    "list_msk_clusters": (
        "msk", Arguments,
        "List bounded provisioned/serverless MSK configuration; no brokers' endpoints, topics, or messages.",
    ),
}

DATA_FIELDS = {
    "kind", "id", "name", "arn", "region", "created_at", "state",
    "encryption_enabled", "encryption_algorithms", "block_public_acls",
    "ignore_public_acls", "block_public_policy", "restrict_public_buckets",
    "policy_public", "versioning_status", "security_checks",
    "billing_mode", "encryption_status", "point_in_time_recovery",
    "deletion_protection_enabled", "item_count", "table_size_bytes",
    "read_capacity_units", "write_capacity_units", "stream_enabled",
    "engine", "engine_version", "node_type", "node_count", "replication_group_id",
    "availability_zone", "encryption_at_rest_enabled", "transit_encryption_enabled",
    "auth_token_enabled", "auto_minor_version_upgrade", "engine_type",
    "processing", "created", "instance_type", "instance_count", "vpc_id",
    "node_to_node_encryption_enabled", "https_required", "advanced_security_enabled",
    "cluster_type", "kafka_version", "broker_count", "client_broker_encryption",
    "in_cluster_encryption_enabled", "unauthenticated_enabled",
    "iam_authentication_enabled", "scram_authentication_enabled", "tls_authentication_enabled",
}


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _nested(value, *keys):
    for key in keys:
        value = _mapping(value).get(key)
    return value


def _text(value, limit=256):
    return value if isinstance(value, str) and 0 < len(value) <= limit else None


def _boolean(value):
    return value if type(value) is bool else None


def _number(value):
    return value if type(value) is int and value >= 0 else None


def _enabled(value, enabled="ENABLED", disabled="DISABLED"):
    return True if value == enabled else False if value == disabled else None


def _inverse(value):
    return None if value is None else not value


def _all_enabled(values):
    if any(value is False for value in values):
        return False
    return True if all(value is True for value in values) else None


def _check(identifier, value, severity="medium"):
    return {
        "id": identifier,
        "status": "pass" if value is True else "fail" if value is False else "unknown",
        "severity": severity,
    }


class ConfigurationInventory:
    def __init__(self, engine):
        self.engine = engine
        self.settings = engine.settings

    def _safe_read(self, obs, service, api, operation, **params):
        # Imported only when invoked: engine imports this module for registration.
        from .engine import QueryStopped

        try:
            return self.engine.call(obs, service, api, operation, **params)
        except QueryStopped:
            # Independent detail reads can still contribute evidence. The engine
            # has already recorded this failed call, denial flag, and error code.
            return {}

    def _arn_in_scope(self, obs, arn, service, api, arn_service, resource_prefix, *, identifier=None):
        if arn is None:
            return True  # Name-only reads still use the verified account's regional client.
        parts = arn.split(":", 5) if isinstance(arn, str) else []
        if (
            len(parts) == 6
            and parts[:5] == [
                "arn", "aws", arn_service, self.settings.target_region, self.settings.expected_account_id,
            ]
            and (
                parts[5] == resource_prefix
                or (
                    resource_prefix.endswith("/")
                    and parts[5].startswith(resource_prefix)
                    and len(parts[5]) > len(resource_prefix)
                )
            )
        ):
            return True
        obs.error("ResourceOutsideScope", service, api, resource_id=identifier, kind="scope_error")
        return False

    def _regional_buckets(self, obs, response):
        rows = []
        for row in response.get("Buckets", []):
            name = _text(row.get("Name"), 63)
            if name is None:
                continue
            if row.get("BucketRegion") != self.settings.target_region:
                obs.error("ResourceScopeUnverified", "s3", "ListBuckets", resource_id=name, kind="scope_error")
                continue
            rows.append(row)
        return rows

    def _bucket_row(self, row):
        return {
            "kind": "s3_bucket", "id": _text(row.get("Name"), 63),
            "name": _text(row.get("Name"), 63), "region": self.settings.target_region,
            "created_at": _text(timestamp(row.get("CreationDate")), 40),
        }

    def list_s3_buckets(self, obs):
        obs.result["notes"].append("Owned general-purpose buckets only; directory buckets are not queried.")
        self.engine.paginate(
            obs, "s3", "ListBuckets", self.engine.client("s3").list_buckets,
            {"BucketRegion": self.settings.target_region, "MaxBuckets": self.settings.max_resources},
            lambda response: self._regional_buckets(obs, response), self._bucket_row,
            "ContinuationToken", "ContinuationToken",
        )

    def _find_bucket(self, obs, bucket):
        params = {
            "BucketRegion": self.settings.target_region,
            "MaxBuckets": self.settings.max_resources,
            "Prefix": bucket,
        }
        seen = set()
        for _ in range(self.settings.max_pages):
            response = self.engine.call(
                obs, "s3", "ListBuckets", self.engine.client("s3").list_buckets, **params
            )
            for row in self._regional_buckets(obs, response):
                if row["Name"] == bucket:
                    return self._bucket_row(row)
            token = response.get("ContinuationToken")
            if not token:
                obs.result["pagination_complete"] = True
                obs.result["missing_resource_ids"].append(bucket)
                obs.error("ResourceNotInScope", "s3", "ListBuckets", resource_id=bucket, kind="scope_error")
                return None
            if token in seen:
                obs.error("RepeatedPaginationToken", "s3", "ListBuckets")
                return None
            seen.add(token)
            params["ContinuationToken"] = token
        obs.result["truncated"] = True
        obs.result["missing_resource_ids"].append(bucket)
        return None

    def get_s3_bucket_configuration(self, obs, bucket):
        obs.result["scope"]["requested_resource_ids"] = [bucket]
        row = self._find_bucket(obs, bucket)
        if row is None:
            return
        obs.result["data"].append(row)
        client = self.engine.client("s3")
        params = {"Bucket": bucket, "ExpectedBucketOwner": self.settings.expected_account_id}
        encryption = self._safe_read(obs, "s3", "GetBucketEncryption", client.get_bucket_encryption, **params)
        public = self._safe_read(obs, "s3", "GetPublicAccessBlock", client.get_public_access_block, **params)
        policy = self._safe_read(obs, "s3", "GetBucketPolicyStatus", client.get_bucket_policy_status, **params)
        versioning = self._safe_read(obs, "s3", "GetBucketVersioning", client.get_bucket_versioning, **params)
        rules = _nested(encryption, "ServerSideEncryptionConfiguration", "Rules")
        algorithms = [
            _text(_nested(rule, "ApplyServerSideEncryptionByDefault", "SSEAlgorithm"))
            for rule in rules
        ] if isinstance(rules, list) else []
        known_algorithms = {"AES256", "aws:kms", "aws:kms:dsse"}
        encrypted = True if algorithms and all(item in known_algorithms for item in algorithms) else None
        flags = {
            target: _boolean(_nested(public, "PublicAccessBlockConfiguration", source))
            for target, source in [
                ("block_public_acls", "BlockPublicAcls"), ("ignore_public_acls", "IgnorePublicAcls"),
                ("block_public_policy", "BlockPublicPolicy"), ("restrict_public_buckets", "RestrictPublicBuckets"),
            ]
        }
        is_public = _boolean(_nested(policy, "PolicyStatus", "IsPublic"))
        version = _text(versioning.get("Status"))
        row.update(
            **flags,
            encryption_enabled=encrypted,
            encryption_algorithms=sorted({item for item in algorithms if item in known_algorithms}),
            policy_public=is_public,
            versioning_status=version,
            security_checks=[
                _check("s3_encryption_enabled", encrypted),
                _check("s3_bucket_public_access_block", _all_enabled(list(flags.values())), "high"),
                _check("s3_bucket_policy_not_public", _inverse(is_public), "high"),
                _check("s3_versioning_enabled", _enabled(version, "Enabled", "Suspended")),
            ],
        )
        obs.result["pagination_complete"] = True
        obs.result["notes"].append(
            "Bucket-level flags only; account access blocks, ACLs, access points, and effective permissions are not assessed."
        )

    def list_dynamodb_tables(self, obs):
        self.engine.paginate(
            obs, "dynamodb", "ListTables", self.engine.client("dynamodb").list_tables,
            {"Limit": self.settings.max_resources}, lambda response: response.get("TableNames", []),
            lambda name: {"kind": "dynamodb_table", "id": _text(name), "name": _text(name)},
            "ExclusiveStartTableName", "LastEvaluatedTableName",
        )

    def get_dynamodb_table_configuration(self, obs, table_name):
        obs.result["scope"]["requested_resource_ids"] = [table_name]
        client = self.engine.client("dynamodb")
        response = self.engine.call(obs, "dynamodb", "DescribeTable", client.describe_table, TableName=table_name)
        table = _mapping(response.get("Table"))
        if table.get("TableName") != table_name:
            obs.error("ResourceNotReturned", "dynamodb", "DescribeTable", resource_id=table_name)
            obs.result["missing_resource_ids"].append(table_name)
            return
        if not self._arn_in_scope(
            obs, table.get("TableArn"), "dynamodb", "DescribeTable", "dynamodb",
            f"table/{table_name}", identifier=table_name,
        ):
            return
        encryption = _text(_nested(table, "SSEDescription", "Status"))
        row = {
            "kind": "dynamodb_table", "id": table_name, "name": table_name,
            "arn": _text(table.get("TableArn"), 2048),
            "state": _text(table.get("TableStatus")),
            "created_at": _text(timestamp(table.get("CreationDateTime")), 40),
            "billing_mode": _text(_nested(table, "BillingModeSummary", "BillingMode")),
            "encryption_status": encryption,
            "deletion_protection_enabled": _boolean(table.get("DeletionProtectionEnabled")),
            "item_count": _number(table.get("ItemCount")),
            "table_size_bytes": _number(table.get("TableSizeBytes")),
            "read_capacity_units": _number(_nested(table, "ProvisionedThroughput", "ReadCapacityUnits")),
            "write_capacity_units": _number(_nested(table, "ProvisionedThroughput", "WriteCapacityUnits")),
            "stream_enabled": _boolean(_nested(table, "StreamSpecification", "StreamEnabled")),
        }
        obs.result["data"].append(row)
        backups = self._safe_read(
            obs, "dynamodb", "DescribeContinuousBackups", client.describe_continuous_backups, TableName=table_name
        )
        pitr = _text(_nested(
            backups, "ContinuousBackupsDescription", "PointInTimeRecoveryDescription", "PointInTimeRecoveryStatus"
        ))
        row.update(
            point_in_time_recovery=pitr,
            security_checks=[
                _check("dynamodb_encryption_enabled", _enabled(encryption)),
                _check("dynamodb_point_in_time_recovery", _enabled(pitr)),
            ],
        )
        obs.result["pagination_complete"] = True

    def _cache_rows(self, obs, response):
        return [
            row for row in response.get("CacheClusters", [])
            if _text(row.get("CacheClusterId")) and self._arn_in_scope(
                obs, row.get("ARN"), "elasticache", "DescribeCacheClusters", "elasticache",
                f"cluster:{row['CacheClusterId']}", identifier=_text(row.get("CacheClusterId")),
            )
        ]

    @staticmethod
    def _cache_row(row):
        at_rest = _boolean(row.get("AtRestEncryptionEnabled"))
        transit = _boolean(row.get("TransitEncryptionEnabled"))
        return {
            "kind": "elasticache_cluster", "id": _text(row.get("CacheClusterId")),
            "arn": _text(row.get("ARN"), 2048),
            "engine": _text(row.get("Engine")), "engine_version": _text(row.get("EngineVersion")),
            "state": _text(row.get("CacheClusterStatus")), "node_type": _text(row.get("CacheNodeType")),
            "node_count": _number(row.get("NumCacheNodes")),
            "replication_group_id": _text(row.get("ReplicationGroupId")),
            "availability_zone": _text(row.get("PreferredAvailabilityZone")),
            "created_at": _text(timestamp(row.get("CacheClusterCreateTime")), 40),
            "encryption_at_rest_enabled": at_rest, "transit_encryption_enabled": transit,
            "auth_token_enabled": _boolean(row.get("AuthTokenEnabled")),
            "auto_minor_version_upgrade": _boolean(row.get("AutoMinorVersionUpgrade")),
            "security_checks": [
                _check("elasticache_encryption_at_rest", at_rest),
                _check("elasticache_encryption_in_transit", transit),
            ],
        }

    def list_elasticache_clusters(self, obs):
        obs.result["notes"].append(
            "Provisioned cache clusters only. Serverless caches and RBAC are not queried; AUTH-token flags do not establish effective authentication."
        )
        self.engine.paginate(
            obs, "elasticache", "DescribeCacheClusters", self.engine.client("elasticache").describe_cache_clusters,
            {"MaxRecords": max(20, self.settings.max_resources), "ShowCacheNodeInfo": False},
            lambda response: self._cache_rows(obs, response), self._cache_row, "Marker", "Marker",
        )

    def list_opensearch_domains(self, obs):
        response = self.engine.call(
            obs, "opensearch", "ListDomainNames", self.engine.client("opensearch").list_domain_names
        )
        rows = response.get("DomainNames", [])
        obs.result["data"] = [{
            "kind": "opensearch_domain", "id": _text(row.get("DomainName")),
            "name": _text(row.get("DomainName")), "engine_type": _text(row.get("EngineType")),
        } for row in rows[:self.settings.max_resources]]
        obs.result["truncated"] = len(rows) > self.settings.max_resources
        obs.result["pagination_complete"] = not obs.result["truncated"]

    def get_opensearch_domain_configuration(self, obs, domain_name):
        obs.result["scope"]["requested_resource_ids"] = [domain_name]
        response = self.engine.call(
            obs, "opensearch", "DescribeDomain", self.engine.client("opensearch").describe_domain,
            DomainName=domain_name,
        )
        domain = _mapping(response.get("DomainStatus"))
        if domain.get("DomainName") != domain_name:
            obs.error("ResourceNotReturned", "opensearch", "DescribeDomain", resource_id=domain_name)
            obs.result["missing_resource_ids"].append(domain_name)
            return
        if not self._arn_in_scope(
            obs, domain.get("ARN"), "opensearch", "DescribeDomain", "es",
            f"domain/{domain_name}", identifier=domain_name,
        ):
            return
        at_rest = _boolean(_nested(domain, "EncryptionAtRestOptions", "Enabled"))
        node_encryption = _boolean(_nested(domain, "NodeToNodeEncryptionOptions", "Enabled"))
        https = _boolean(_nested(domain, "DomainEndpointOptions", "EnforceHTTPS"))
        security = _boolean(_nested(domain, "AdvancedSecurityOptions", "Enabled"))
        obs.result["data"] = [{
            "kind": "opensearch_domain", "id": domain_name, "name": domain_name,
            "arn": _text(domain.get("ARN"), 2048),
            "engine_version": _text(domain.get("EngineVersion")),
            "state": _text(domain.get("DomainProcessingStatus")),
            "processing": _boolean(domain.get("Processing")), "created": _boolean(domain.get("Created")),
            "instance_type": _text(_nested(domain, "ClusterConfig", "InstanceType")),
            "instance_count": _number(_nested(domain, "ClusterConfig", "InstanceCount")),
            "vpc_id": _text(_nested(domain, "VPCOptions", "VPCId")),
            "encryption_at_rest_enabled": at_rest,
            "node_to_node_encryption_enabled": node_encryption,
            "https_required": https, "advanced_security_enabled": security,
            "security_checks": [
                _check("opensearch_encryption_at_rest", at_rest),
                _check("opensearch_node_to_node_encryption", node_encryption),
                _check("opensearch_https_required", https, "high"),
                _check("opensearch_advanced_security_enabled", security),
            ],
        }]
        obs.result["pagination_complete"] = True

    def _msk_rows(self, obs, response):
        return [
            row for row in response.get("ClusterInfoList", [])
            if _text(row.get("ClusterName")) and self._arn_in_scope(
                obs, row.get("ClusterArn"), "msk", "ListClustersV2", "kafka",
                f"cluster/{row['ClusterName']}/", identifier=_text(row.get("ClusterName")),
            )
        ]

    @staticmethod
    def _msk_row(row):
        provisioned = _mapping(row.get("Provisioned"))
        details = _mapping(row.get("Serverless")) if row.get("ClusterType") == "SERVERLESS" else provisioned
        auth = _mapping(details.get("ClientAuthentication"))
        # Only an observed nonempty encryption key reference proves this flag;
        # the reference itself is never returned.
        at_rest = True if _text(_nested(
            provisioned, "EncryptionInfo", "EncryptionAtRest", "DataVolumeKMSKeyId"
        ), 2048) else None
        client_tls = _text(_nested(provisioned, "EncryptionInfo", "EncryptionInTransit", "ClientBroker"))
        in_cluster = _boolean(_nested(provisioned, "EncryptionInfo", "EncryptionInTransit", "InCluster"))
        unauthenticated = _boolean(_nested(auth, "Unauthenticated", "Enabled"))
        tls_only = True if client_tls == "TLS" else False if client_tls in {"TLS_PLAINTEXT", "PLAINTEXT"} else None
        return {
            "kind": "msk_cluster", "id": _text(row.get("ClusterArn"), 2048) or _text(row.get("ClusterName")),
            "name": _text(row.get("ClusterName")), "arn": _text(row.get("ClusterArn"), 2048),
            "state": _text(row.get("State")), "cluster_type": _text(row.get("ClusterType")),
            "created_at": _text(timestamp(row.get("CreationTime")), 40),
            "kafka_version": _text(_nested(provisioned, "CurrentBrokerSoftwareInfo", "KafkaVersion")),
            "broker_count": _number(provisioned.get("NumberOfBrokerNodes")),
            "instance_type": _text(_nested(provisioned, "BrokerNodeGroupInfo", "InstanceType")),
            "encryption_at_rest_enabled": at_rest, "client_broker_encryption": client_tls,
            "in_cluster_encryption_enabled": in_cluster, "unauthenticated_enabled": unauthenticated,
            "iam_authentication_enabled": _boolean(_nested(auth, "Sasl", "Iam", "Enabled")),
            "scram_authentication_enabled": _boolean(_nested(auth, "Sasl", "Scram", "Enabled")),
            "tls_authentication_enabled": _boolean(_nested(auth, "Tls", "Enabled")),
            "security_checks": [
                _check("msk_encryption_at_rest", at_rest),
                _check("msk_client_tls_only", tls_only),
                _check("msk_in_cluster_encryption", in_cluster),
                _check("msk_unauthenticated_access_disabled", _inverse(unauthenticated), "high"),
            ],
        }

    def list_msk_clusters(self, obs):
        self.engine.paginate(
            obs, "msk", "ListClustersV2", self.engine.client("kafka").list_clusters_v2,
            {"MaxResults": self.settings.max_resources},
            lambda response: self._msk_rows(obs, response), self._msk_row, "NextToken", "NextToken",
        )


def handlers(engine):
    implementation = ConfigurationInventory(engine)
    return {name: getattr(implementation, name) for name in TOOL_SCHEMAS}
