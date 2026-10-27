"""Allowlist durable BMA output. Never proxy the raw event or item stream."""
import json

from aws_inventory.config_inventory import DATA_FIELDS as CONFIG_DATA_FIELDS
from aws_inventory.network_inventory import DATA_FIELDS as NETWORK_DATA_FIELDS
from aws_inventory.schema import TOOL_SCHEMAS

TOP_FIELDS = {
    "schema_version", "tool", "mode", "account_id", "region", "service", "observed_at", "api_calls",
    "resource_ids", "resource_count", "count", "pagination_complete", "truncated", "permission_denied",
    "errors", "missing_resource_ids", "scope", "notes", "data", "status", "duration_ms", "datapoint_count",
}
DATA_FIELDS = {
    "id", "arn", "name", "instance_type", "state", "availability_zone", "launch_time", "application_health",
    "instance_status", "system_status", "attached_ebs_status", "engine", "engine_version", "instance_class",
    "multi_az", "cluster_arn", "cluster", "desired_count", "running_count", "pending_count",
    "deployments", "deployments_truncated", "function_kind", "runtime", "package_type", "memory_mb",
    "timeout_seconds", "last_modified", "last_update_status", "state_evidence", "alarm_type",
    "state_updated_at", "namespace", "metric_name", "comparison_operator", "threshold", "evaluation_periods",
    "treat_missing_data", "resource_id", "statistic", "period_seconds", "points", "data_status", "status_code",
    "account_id", "account_verified", "app_region", "target_region", "supported_services",
    "lambda_scope", "data_processing_region",
    "data_processing_scope",
    "kind", "vpc_id", "subnet_id", "subnet_ids", "security_group_ids", "relationships_truncated",
    "storage_encrypted", "publicly_accessible", "security_checks",
}
DATA_FIELDS |= CONFIG_DATA_FIELDS | NETWORK_DATA_FIELDS
STATUSES = {"ok", "empty", "partial", "access_denied", "api_error", "invalid_input",
            "unsupported_service", "account_mismatch"}


def _decode(value):
    for _ in range(4):
        if isinstance(value, str):
            if len(value) > 1_000_000:
                raise ValueError("ToolResultTooLarge")
            value = json.loads(value)
        elif isinstance(value, dict) and "structuredContent" in value:
            value = value["structuredContent"]
        elif isinstance(value, dict) and isinstance(value.get("content"), list):
            texts = [c.get("text", "") for c in value["content"] if c.get("type") == "text"]
            value = "\n".join(texts)
        else:
            break
    if not isinstance(value, dict):
        raise ValueError("InvalidToolResult")
    return value


def sanitize_result(value, settings, tool):
    if value.get("tool") != tool or value.get("status") not in STATUSES:
        raise ValueError("InvalidToolResult")
    if value.get("region") != settings.target_region:
        raise ValueError("EvidenceRegionMismatch")
    if value.get("mode") != settings.mode:
        raise ValueError("EvidenceModeMismatch")
    # Preserve a genuine blocked-account result, but never treat its data as evidence.
    if value.get("account_id") != settings.expected_account_id:
        identity_failed = value.get("account_id") is None and not value.get("data") and any(
            c.get("api") == "GetCallerIdentity" and c.get("success") is False for c in value.get("api_calls", [])
        )
        if not identity_failed and (value.get("status") != "account_mismatch" or value.get("data")):
            raise ValueError("EvidenceAccountMismatch")
    if not isinstance(value.get("data"), list) or not isinstance(value.get("api_calls"), list):
        raise ValueError("InvalidToolResult")
    result = {key: value[key] for key in TOP_FIELDS if key in value}
    result["data"] = []
    for row in value["data"][:100]:
        if not isinstance(row, dict):
            raise ValueError("InvalidToolRow")
        item = {key: row[key] for key in DATA_FIELDS if key in row}
        if "points" in item:
            item["points"] = [{"timestamp": p.get("timestamp"), "value": p.get("value")}
                              for p in item["points"][:1440]]
        if "deployments" in item:
            keys = {"id", "status", "rollout_state", "desired_count", "running_count", "pending_count",
                    "created_at", "updated_at"}
            item["deployments"] = [{k: d[k] for k in keys if k in d} for d in item["deployments"][:10]]
        if "security_checks" in item:
            item["security_checks"] = [
                {key: check[key] for key in ("id", "status", "severity") if key in check}
                for check in item["security_checks"][:20]
                if isinstance(check, dict) and check.get("status") in {"pass", "fail", "unknown"}
            ]
        if "ingress_rules" in item:
            keys = {"protocol", "from_port", "to_port", "source_type", "source", "unrestricted"}
            item["ingress_rules"] = [{key: rule[key] for key in keys if key in rule}
                                     for rule in item["ingress_rules"][:50] if isinstance(rule, dict)]
        for key in ("subnet_ids", "security_group_ids", "attached_instance_ids"):
            if key in item:
                item[key] = [value[:256] for value in item[key][:100] if isinstance(value, str)]
        result["data"].append(item)
    return result


def public_items(items, settings):
    answers, evidence, errors, seen = [], [], [], set()
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        if item_id and item_id in seen:
            continue
        if item_id:
            seen.add(item_id)
        kind = item.get("type")
        if kind == "message" and item.get("role") == "assistant" and item.get("channel") in {None, "final"}:
            answers.extend(
                c["text"][:40_000] for c in item.get("content", [])
                if isinstance(c, dict) and c.get("type") == "output_text" and isinstance(c.get("text"), str)
            )
        elif kind == "mcp_call" and item.get("server_label") == "seoul_aws" and item.get("name") in TOOL_SCHEMAS:
            try:
                value = _decode(item.get("output", item.get("result")))
                result = sanitize_result(value, settings, item["name"])
                result["item_id"] = item_id
                evidence.append(result)
            except (ValueError, TypeError, KeyError) as exc:
                code = str(exc)
                errors.append(code if code in {
                    "EvidenceAccountMismatch", "EvidenceRegionMismatch", "EvidenceModeMismatch", "ToolResultTooLarge"
                } else "InvalidToolResult")
    return {"answer": "\n\n".join(answers)[:60_000], "evidence": evidence, "evidence_errors": errors}
