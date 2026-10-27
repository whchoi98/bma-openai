from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone

from .engine import QueryStopped, UnsupportedService
from .normalize import timestamp

# Model arguments cannot supply a namespace, dimension, statistic, or period.
METRICS = {
    "ec2": ("AWS/EC2", [("CPUUtilization", "Average"), ("StatusCheckFailed", "Maximum")]),
    "rds": ("AWS/RDS", [("CPUUtilization", "Average"), ("DatabaseConnections", "Average"), ("FreeableMemory", "Average")]),
    "ecs": ("AWS/ECS", [("CPUUtilization", "Average"), ("MemoryUtilization", "Average")]),
    "lambda": ("AWS/Lambda", [("Invocations", "Sum"), ("Errors", "Sum"), ("Throttles", "Sum"), ("Duration", "Average")]),
}


def _time(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Metric timestamps must include a timezone.")
    return parsed.astimezone(timezone.utc)


def collect_metrics(engine, obs, service, resource_id, start_time, end_time):
    if service not in METRICS:
        raise UnsupportedService
    start, end = _time(start_time), _time(end_time)
    now = engine.clock()
    if (
        start >= end
        or end > now + timedelta(seconds=1)
        or end - start > timedelta(hours=engine.settings.max_metric_hours)
        or start < now - timedelta(days=7)
    ):
        raise ValueError("Metric window is outside the configured limits.")
    if service == "ec2":
        if not re.fullmatch(r"i-(?:[0-9a-f]{8}|[0-9a-f]{17})", resource_id):
            raise ValueError("Invalid instance ID.")
        dimensions = [{"Name": "InstanceId", "Value": resource_id}]
    elif service == "ecs":
        resource_id = engine.identifier(resource_id, "ecs", "service", allow_path=True)
        if "/" not in resource_id:
            raise ValueError("ECS metrics require cluster/service.")
        cluster, name = resource_id.split("/")
        dimensions = [{"Name": "ClusterName", "Value": cluster}, {"Name": "ServiceName", "Value": name}]
    else:
        resource_id = engine.identifier(resource_id, service, "function" if service == "lambda" else "db")
        dimensions = [{"Name": "FunctionName" if service == "lambda" else "DBInstanceIdentifier", "Value": resource_id}]
    namespace, definitions = METRICS[service]
    period = engine.settings.metric_period_seconds
    queries = [
        {"Id": f"m{i}", "MetricStat": {
            "Metric": {"Namespace": namespace, "MetricName": metric, "Dimensions": dimensions},
            "Period": period, "Stat": stat,
        }, "ReturnData": True}
        for i, (metric, stat) in enumerate(definitions)
    ]
    obs.result["scope"].update(
        resource_id=resource_id, namespace=namespace, dimensions=dimensions,
        start_time=timestamp(start), end_time=timestamp(end), period_seconds=period,
        max_datapoints=engine.settings.max_datapoints,
        resource_existence="not_established_by_metrics",
    )
    obs.result["notes"].append(
        "지표 버킷은 300초입니다. 결측은 0이 아니며, 지표 조회만으로 리소스 존재나 앱 정상 여부를 판단할 수 없습니다."
    )
    rows = {
        f"m{i}": {
            "resource_id": resource_id, "metric_name": metric, "namespace": namespace,
            "statistic": stat, "period_seconds": period, "points": [],
            "data_status": "unknown", "status_code": None,
        }
        for i, (metric, stat) in enumerate(definitions)
    }
    params = {
        "MetricDataQueries": queries, "StartTime": start, "EndTime": end,
        "ScanBy": "TimestampAscending", "MaxDatapoints": engine.settings.max_datapoints,
    }
    seen_tokens = set()
    seen_points = {key: set() for key in rows}
    total = 0
    succeeded = False
    try:
        for _ in range(engine.settings.max_pages):
            response = engine.call(
                obs, "cloudwatch", "GetMetricData", engine.client("cloudwatch").get_metric_data, **params
            )
            succeeded = True
            for message in response.get("Messages", []):
                code = "MetricDataMessage"
                if message.get("Code") in {"MaxMetricsExceeded", "MaxMetricsExceededException"}:
                    code = "MaxMetricsExceeded"
                obs.error(code, "cloudwatch", "GetMetricData")
            for result in response.get("MetricDataResults", []):
                key = result.get("Id")
                if key not in rows:
                    obs.error("UnexpectedMetricResult", "cloudwatch", "GetMetricData")
                    continue
                row = rows[key]
                row["status_code"] = result.get("StatusCode")
                values, times = result.get("Values", []), result.get("Timestamps", [])
                if len(values) != len(times):
                    obs.error("MismatchedMetricArrays", "cloudwatch", "GetMetricData")
                for time, value in zip(times, values):
                    point_time = timestamp(time)
                    if point_time in seen_points[key]:
                        continue
                    if total >= engine.settings.max_datapoints:
                        obs.result["truncated"] = True
                        break
                    if not isinstance(value, (int, float)) or not math.isfinite(value):
                        obs.error("InvalidMetricValue", "cloudwatch", "GetMetricData")
                        continue
                    seen_points[key].add(point_time)
                    row["points"].append({"timestamp": point_time, "value": value})
                    total += 1
            token = response.get("NextToken")
            if obs.result["truncated"] or (token and total >= engine.settings.max_datapoints):
                obs.result["truncated"] = True
                break
            if not token:
                obs.result["pagination_complete"] = True
                break
            if token in seen_tokens:
                obs.error("RepeatedPaginationToken", "cloudwatch", "GetMetricData")
                break
            seen_tokens.add(token)
            params = {**params, "NextToken": token}
        else:
            obs.result["truncated"] = True
    except QueryStopped:
        pass
    if succeeded:
        for row in rows.values():
            code = row["status_code"]
            row["points"].sort(key=lambda point: point["timestamp"])
            if code == "Complete":
                row["data_status"] = "complete" if row["points"] else "no_data"
            elif code == "PartialData":
                row["data_status"] = "partial"
                obs.error("PartialData", "cloudwatch", "GetMetricData", resource_id=resource_id)
            elif code == "Forbidden":
                row["data_status"] = "forbidden"
                obs.error("Forbidden", "cloudwatch", "GetMetricData", resource_id=resource_id, kind="access_denied")
            else:
                row["data_status"] = "error"
                obs.error("MissingMetricResult" if code is None else "MetricInternalError",
                          "cloudwatch", "GetMetricData", resource_id=resource_id)
            if not obs.result["pagination_complete"] and code in {"Complete", "PartialData"}:
                row["data_status"] = "partial" if row["points"] else "unknown"
        obs.result["data"] = list(rows.values())
    obs.result["datapoint_count"] = total
    if not obs.result["errors"] and not obs.result["truncated"] and succeeded:
        obs.forced_status = "ok" if total else "empty"
    elif succeeded and not total and all(row["data_status"] == "forbidden" for row in rows.values()):
        obs.forced_status = "access_denied"
    elif succeeded and not total and all(row["data_status"] in {"error", "forbidden", "unknown"} for row in rows.values()) and not obs.result["truncated"]:
        obs.forced_status = "access_denied" if obs.result["permission_denied"] else "api_error"
