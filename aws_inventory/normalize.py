from datetime import datetime, timezone


def timestamp(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return value if isinstance(value, str) else None


def ec2(row):
    return {
        "id": row.get("InstanceId"),
        "kind": "ec2",
        "vpc_id": row.get("VpcId"),
        "subnet_id": row.get("SubnetId"),
        "security_group_ids": [g["GroupId"] for g in row.get("SecurityGroups", [])[:20] if "GroupId" in g],
        "relationships_truncated": len(row.get("SecurityGroups", [])) > 20,
        "instance_type": row.get("InstanceType"),
        "state": row.get("State", {}).get("Name"),
        "availability_zone": row.get("Placement", {}).get("AvailabilityZone"),
        "launch_time": timestamp(row.get("LaunchTime")),
        "application_health": "not_assessed",
    }


def ec2_health(row):
    return {
        "id": row.get("InstanceId"),
        "state": row.get("InstanceState", {}).get("Name"),
        "instance_status": row.get("InstanceStatus", {}).get("Status"),
        "system_status": row.get("SystemStatus", {}).get("Status"),
        "attached_ebs_status": row.get("AttachedEbsStatus", {}).get("Status"),
        "availability_zone": row.get("AvailabilityZone"),
        "application_health": "not_assessed",
    }


def rds(row):
    encrypted = row.get("StorageEncrypted") if type(row.get("StorageEncrypted")) is bool else None
    public = row.get("PubliclyAccessible") if type(row.get("PubliclyAccessible")) is bool else None
    subnet_group = row.get("DBSubnetGroup") or {}
    return {
        "id": row.get("DBInstanceIdentifier"),
        "kind": "rds",
        "arn": row.get("DBInstanceArn"),
        "state": row.get("DBInstanceStatus"),
        "engine": row.get("Engine"),
        "engine_version": row.get("EngineVersion"),
        "instance_class": row.get("DBInstanceClass"),
        "multi_az": row.get("MultiAZ"),
        "availability_zone": row.get("AvailabilityZone"),
        "vpc_id": subnet_group.get("VpcId"),
        "subnet_ids": [s["SubnetIdentifier"] for s in subnet_group.get("Subnets", [])[:20] if "SubnetIdentifier" in s],
        "relationships_truncated": len(subnet_group.get("Subnets", [])) > 20,
        "storage_encrypted": encrypted,
        "publicly_accessible": public,
        "security_checks": [
            {"id": "rds_encrypted", "status": "unknown" if encrypted is None else "pass" if encrypted else "fail", "severity": "high"},
            {"id": "rds_not_public", "status": "unknown" if public is None else "fail" if public else "pass", "severity": "high"},
        ],
        "application_health": "not_assessed",
    }


def ecs_health(row):
    return {
        "id": row.get("serviceArn"),
        "name": row.get("serviceName"),
        "cluster_arn": row.get("clusterArn"),
        "state": row.get("status"),
        "desired_count": row.get("desiredCount"),
        "running_count": row.get("runningCount"),
        "pending_count": row.get("pendingCount"),
        "deployments": [
            {
                "id": deployment.get("id"),
                "status": deployment.get("status"),
                "rollout_state": deployment.get("rolloutState"),
                "desired_count": deployment.get("desiredCount"),
                "running_count": deployment.get("runningCount"),
                "pending_count": deployment.get("pendingCount"),
                "created_at": timestamp(deployment.get("createdAt")),
                "updated_at": timestamp(deployment.get("updatedAt")),
            }
            for deployment in row.get("deployments", [])[:10]
        ],
        "deployments_truncated": len(row.get("deployments", [])) > 10,
        "application_health": "not_assessed",
    }


def lambda_function(row, *, configuration=False):
    return {
        "id": row.get("FunctionName"),
        "arn": row.get("FunctionArn"),
        "function_kind": "event",
        "runtime": row.get("Runtime"),
        "package_type": row.get("PackageType"),
        "memory_mb": row.get("MemorySize"),
        "timeout_seconds": row.get("Timeout"),
        "last_modified": row.get("LastModified"),
        "state": row.get("State") if configuration else None,
        "last_update_status": row.get("LastUpdateStatus") if configuration else None,
        "state_evidence": "GetFunctionConfiguration" if configuration else "not_returned_by_ListFunctions",
        "application_health": "not_assessed",
    }


def alarm(row):
    return {
        "id": row.get("AlarmArn") or row.get("AlarmName"),
        "name": row.get("AlarmName"),
        "alarm_type": row["_alarm_type"],
        "state": row.get("StateValue"),
        "state_updated_at": timestamp(row.get("StateUpdatedTimestamp")),
        "namespace": row.get("Namespace"),
        "metric_name": row.get("MetricName"),
        "comparison_operator": row.get("ComparisonOperator"),
        "threshold": row.get("Threshold"),
        "evaluation_periods": row.get("EvaluationPeriods"),
        "treat_missing_data": row.get("TreatMissingData"),
        "application_health": "not_assessed",
    }
