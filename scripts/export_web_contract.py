#!/usr/bin/env python3
# ruff: noqa: E402
"""Export Python tool contracts and synthetic fixtures for the Node Web Function."""
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aws_inventory.config import SUPPORTED_SERVICES, Settings
from aws_inventory.config_samples import BUCKET, DOMAIN, TABLE
from aws_inventory.engine import AwsInventory
from aws_inventory.network_samples import VPC
from aws_inventory.sample import CLUSTER, INSTANCE_A, INSTANCE_B, SERVICE
from aws_inventory.schema import TOOL_SCHEMAS
from webapp.bma import INSTRUCTIONS
from webapp.evidence import DATA_FIELDS, STATUSES, TOP_FIELDS


def main():
    contract = {
        "schema_version": "1.0",
        "tools": list(TOOL_SCHEMAS),
        "supported_services": list(SUPPORTED_SERVICES),
        "top_fields": sorted(TOP_FIELDS),
        "data_fields": sorted(DATA_FIELDS),
        "statuses": sorted(STATUSES),
        "instructions": INSTRUCTIONS,
        "skills": [
            {"name": path.parent.name, "markdown": path.read_text(),
             "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in sorted((ROOT / "skills").glob("*/SKILL.md"))
        ],
    }
    now = datetime(2026, 10, 26, 0, 0, tzinfo=timezone.utc)
    engine = AwsInventory(Settings(expected_account_id="000000000000", mode="sample"), clock=lambda: now)
    calls = [
        ("get_account_context", {}),
        ("list_ec2_instances", {}),
        ("get_ec2_instance_health", {"instance_ids": [INSTANCE_A, INSTANCE_B]}),
        ("list_rds_instances", {}),
        ("list_ecs_clusters", {}),
        ("list_ecs_services", {"cluster": CLUSTER}),
        ("get_ecs_service_health", {"cluster": CLUSTER, "services": [SERVICE]}),
        ("list_lambda_functions", {}),
        ("get_lambda_function_health", {"function_name": "sample-worker"}),
        ("list_cloudwatch_alarms", {"state": "ALARM"}),
        ("list_vpcs", {}),
        ("get_vpc_topology", {"vpc_id": VPC}),
        ("list_security_groups", {"vpc_id": VPC}),
        ("list_ebs_volumes", {}),
        ("list_ecr_repositories", {}),
        ("list_s3_buckets", {}),
        ("get_s3_bucket_configuration", {"bucket": BUCKET}),
        ("list_dynamodb_tables", {}),
        ("get_dynamodb_table_configuration", {"table_name": TABLE}),
        ("list_elasticache_clusters", {}),
        ("list_opensearch_domains", {}),
        ("get_opensearch_domain_configuration", {"domain_name": DOMAIN}),
        ("list_msk_clusters", {}),
    ]
    for function in ["sample-worker", "sample-idle"]:
        calls.append(("get_resource_metrics", {
            "service": "lambda", "resource_id": function,
            "start_time": (now - timedelta(hours=1)).isoformat(), "end_time": now.isoformat(),
        }))
    samples = {}
    for name, args in calls:
        result = engine.invoke(name, args)
        assert result["status"] in {"ok", "empty", "partial"}, result
        result["duration_ms"] = 0
        for api in result["api_calls"]:
            api["duration_ms"] = 0
        key = name + (":" + args["resource_id"] if name == "get_resource_metrics" else "")
        samples[key] = result
    for filename, data in [("contract.json", contract), ("sample-data.json", samples)]:
        (ROOT / "web" / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
