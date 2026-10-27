from __future__ import annotations

import re
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from time import monotonic

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from . import config_inventory, network_inventory, normalize
from .config import SDK_SERVICES, SUPPORTED_SERVICES, Settings
from .schema import TOOL_SCHEMAS

ACCESS_DENIED = {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation", "Forbidden", "ForbiddenException"}
MAX_API_CALLS = 31


class QueryStopped(Exception):
    pass


class UnsupportedService(Exception):
    pass


class Observation:
    def __init__(self, settings: Settings, name: str, service: str, now: datetime):
        self.started = monotonic()
        self.result = {
            "schema_version": "1.0",
            "tool": name,
            "mode": settings.mode,
            "account_id": None,
            "region": settings.target_region,
            "service": service,
            "observed_at": normalize.timestamp(now),
            "api_calls": [],
            "resource_ids": [],
            "pagination_complete": False,
            "truncated": False,
            "permission_denied": False,
            "errors": [],
            "missing_resource_ids": [],
            "scope": {"max_resources": settings.max_resources, "max_pages": settings.max_pages, "max_api_calls": MAX_API_CALLS},
            "notes": [],
            "data": [],
        }
        self.forced_status = None

    def error(self, code, service, api=None, *, resource_id=None, kind="api_error"):
        error = {"code": code, "service": service, "api": api, "kind": kind}
        if resource_id is not None:
            error["resource_id"] = resource_id
        self.result["errors"].append(error)
        if kind == "access_denied":
            self.result["permission_denied"] = True

    def finish(self):
        r = self.result
        r["count"] = len(r["data"])
        r["resource_ids"] = list(dict.fromkeys(
            row.get("resource_id") or row.get("id")
            for row in r["data"] if row.get("resource_id") or row.get("id")
        ))
        r["resource_count"] = len(r["resource_ids"])
        if self.forced_status:
            r["status"] = self.forced_status
        elif r["errors"] and not r["data"]:
            r["status"] = "access_denied" if r["permission_denied"] else "api_error"
        elif r["truncated"] or r["missing_resource_ids"] or (r["data"] and r["errors"]):
            r["status"] = "partial"
        elif r["errors"]:
            r["status"] = "access_denied" if r["permission_denied"] else "api_error"
        else:
            r["status"] = "ok" if r["data"] else "empty"
        r["duration_ms"] = round((monotonic() - self.started) * 1000, 3)
        return r


class AwsInventory:
    """Only explicit methods below issue AWS queries. Model input cannot select an SDK operation."""

    def __init__(self, settings: Settings, *, session=None, clock=None):
        self.settings = settings
        if session is None and settings.mode == "sample":
            from .sample import SampleSession
            session = SampleSession()
        self.session = session if session is not None else boto3.Session()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._clients = {}
        self._client_lock = threading.RLock()
        self.sdk_config = Config(
            connect_timeout=3,
            read_timeout=10,
            retries={"mode": "standard", "total_max_attempts": 3},
            user_agent_extra="bma-seoul-inventory/0.1",
        )
        self._handlers = {
            "get_account_context": self._account_context,
            "list_ec2_instances": self._ec2_instances,
            "get_ec2_instance_health": self._ec2_health,
            "list_rds_instances": self._rds_instances,
            "list_ecs_clusters": self._ecs_clusters,
            "list_ecs_services": self._ecs_services,
            "get_ecs_service_health": self._ecs_health,
            "list_lambda_functions": self._lambda_functions,
            "get_lambda_function_health": self._lambda_health,
            "get_resource_metrics": self._metrics,
            "list_cloudwatch_alarms": self._alarms,
            **network_inventory.handlers(self),
            **config_inventory.handlers(self),
        }

    def client(self, service):
        if service not in SDK_SERVICES:
            raise ValueError("Unregistered AWS service.")
        with self._client_lock:
            if service not in self._clients:
                region = self.settings.app_region if service == "sts" else self.settings.target_region
                self._clients[service] = self.session.client(
                    service, region_name=region, config=self.sdk_config
                )
            return self._clients[service]

    def invoke(self, name: str, arguments: dict | None = None) -> dict:
        service, model, _ = TOOL_SCHEMAS.get(name, ("unknown", None, None))
        if name == "get_resource_metrics" and isinstance(arguments, dict):
            candidate = arguments.get("service")
            if candidate in SUPPORTED_SERVICES:
                service = candidate
        obs = Observation(self.settings, name, service, self.clock())
        try:
            self._verify_account(obs)
            if model is None:
                raise ValueError("Unknown tool.")
            args = model.model_validate({} if arguments is None else arguments)
            self._handlers[name](obs, **args.model_dump())
        except QueryStopped:
            pass
        except UnsupportedService:
            obs.forced_status = "unsupported_service"
            obs.error("UnsupportedService", service, kind="unsupported_service")
        except (ValidationError, ValueError):
            obs.forced_status = "invalid_input"
            obs.error("InvalidInput", service, kind="invalid_input")
        except BotoCoreError as exc:
            obs.error(type(exc).__name__, service)
        return obs.finish()

    def call(self, obs: Observation, service: str, api: str, operation: Callable, **params):
        if len(obs.result["api_calls"]) >= MAX_API_CALLS:
            obs.result["truncated"] = True
            obs.error("ApiCallLimitReached", service, api, kind="limit")
            raise QueryStopped
        start = monotonic()
        entry = {
            "service": service,
            "api": api,
            "region": self.settings.app_region if service == "sts" else self.settings.target_region,
            "success": False,
        }
        obs.result["api_calls"].append(entry)
        try:
            data = operation(**params)
            metadata = data.get("ResponseMetadata", {})
            entry.update(success=True, retry_attempts=metadata.get("RetryAttempts", 0))
            if metadata.get("RequestId"):
                entry["request_id"] = metadata["RequestId"]
            return data
        except (ClientError, BotoCoreError) as exc:
            code = exc.response["Error"]["Code"] if isinstance(exc, ClientError) else type(exc).__name__
            if isinstance(exc, ClientError):
                metadata = exc.response.get("ResponseMetadata", {})
                entry["retry_attempts"] = metadata.get("RetryAttempts", 0)
                if metadata.get("RequestId"):
                    entry["request_id"] = metadata["RequestId"]
            obs.error(code, service, api, kind="access_denied" if code in ACCESS_DENIED else "api_error")
            raise QueryStopped from None
        finally:
            entry["duration_ms"] = round((monotonic() - start) * 1000, 3)

    def _verify_account(self, obs):
        identity = self.call(obs, "sts", "GetCallerIdentity", self.client("sts").get_caller_identity)
        account = identity.get("Account")
        obs.result["account_id"] = account
        if account != self.settings.expected_account_id:
            obs.forced_status = "account_mismatch"
            obs.error("AccountMismatch", "sts", "GetCallerIdentity", kind="account_mismatch")
            raise QueryStopped

    def paginate(self, obs, service, api, operation, params, extract, normalize_row, request_token, response_token):
        seen = set()
        for _ in range(self.settings.max_pages):
            response = self.call(obs, service, api, operation, **params)
            rows = extract(response)
            room = self.settings.max_resources - len(obs.result["data"])
            obs.result["data"].extend(normalize_row(row) for row in rows[:room])
            token = response.get(response_token)
            if len(rows) > room or (token and len(obs.result["data"]) >= self.settings.max_resources):
                obs.result["truncated"] = True
                return
            if not token:
                obs.result["pagination_complete"] = True
                return
            if token in seen:
                obs.error("RepeatedPaginationToken", service, api)
                return
            seen.add(token)
            params = {**params, request_token: token}
        obs.result["truncated"] = True

    def _account_context(self, obs):
        obs.result["data"] = [{
            "account_id": obs.result["account_id"],
            "account_verified": True,
            "app_region": self.settings.app_region,
            "target_region": self.settings.target_region,
            "supported_services": list(SUPPORTED_SERVICES),
            "lambda_scope": "event_functions_only",
            "data_processing_region": self.settings.app_region if self.settings.model_processing_scope == "app_region" else None,
            "data_processing_scope": self.settings.model_processing_scope,
        }]
        obs.result["pagination_complete"] = True

    def _ec2_instances(self, obs):
        self.paginate(
            obs, "ec2", "DescribeInstances", self.client("ec2").describe_instances,
            {"MaxResults": max(5, min(50, self.settings.max_resources))},
            lambda r: [i for reservation in r.get("Reservations", []) for i in reservation.get("Instances", [])],
            normalize.ec2, "NextToken", "NextToken",
        )

    def _bounded_ids(self, ids):
        if len(ids) > self.settings.max_resources or len(set(ids)) != len(ids):
            raise ValueError("Too many or duplicate resource identifiers.")

    def _ec2_health(self, obs, instance_ids):
        self._bounded_ids(instance_ids)
        obs.result["scope"]["requested_resource_ids"] = instance_ids
        self.paginate(
            obs, "ec2", "DescribeInstanceStatus", self.client("ec2").describe_instance_status,
            {"InstanceIds": instance_ids, "IncludeAllInstances": True},
            lambda r: r.get("InstanceStatuses", []), normalize.ec2_health, "NextToken", "NextToken",
        )
        returned = {row["id"] for row in obs.result["data"]}
        obs.result["missing_resource_ids"] = [i for i in instance_ids if i not in returned]

    def _rds_instances(self, obs):
        self.paginate(
            obs, "rds", "DescribeDBInstances", self.client("rds").describe_db_instances,
            {"MaxRecords": max(20, min(50, self.settings.max_resources))},
            lambda r: r.get("DBInstances", []), normalize.rds, "Marker", "Marker",
        )

    def identifier(self, value, service, resource_type, *, allow_path=False):
        if value.startswith("arn:"):
            parts = value.split(":", 5)
            if len(parts) != 6 or parts[:3] != ["arn", "aws", service]:
                raise ValueError("Unexpected resource ARN.")
            if parts[3:5] != [self.settings.target_region, self.settings.expected_account_id]:
                raise ValueError("Resource ARN is outside the authorized account or Region.")
            prefix = resource_type + (":" if service in {"lambda", "rds"} else "/")
            if not parts[5].startswith(prefix):
                raise ValueError("Unexpected resource type.")
            value = parts[5][len(prefix):]
        pattern = r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)?" if allow_path else r"[A-Za-z0-9_-]+"
        if not re.fullmatch(pattern, value) or len(value) > 255:
            raise ValueError("Invalid resource identifier.")
        return value

    def _ecs_clusters(self, obs):
        self.paginate(
            obs, "ecs", "ListClusters", self.client("ecs").list_clusters,
            {"maxResults": min(50, self.settings.max_resources)},
            lambda r: r.get("clusterArns", []), lambda arn: {"id": arn}, "nextToken", "nextToken",
        )

    def _ecs_services(self, obs, cluster):
        cluster = self.identifier(cluster, "ecs", "cluster")
        obs.result["scope"]["cluster"] = cluster
        self.paginate(
            obs, "ecs", "ListServices", self.client("ecs").list_services,
            {"cluster": cluster, "maxResults": min(50, self.settings.max_resources)},
            lambda r: r.get("serviceArns", []),
            lambda arn: {"id": arn, "cluster": cluster}, "nextToken", "nextToken",
        )

    def _ecs_health(self, obs, cluster, services):
        cluster = self.identifier(cluster, "ecs", "cluster")
        self._bounded_ids(services)
        names = []
        for service in services:
            name = self.identifier(service, "ecs", "service", allow_path=True)
            if "/" in name:
                owning_cluster, name = name.split("/")
                if owning_cluster != cluster:
                    raise ValueError("Service is outside the requested cluster.")
            names.append(name)
        obs.result["scope"].update(cluster=cluster, requested_resource_ids=services)
        response = self.call(
            obs, "ecs", "DescribeServices", self.client("ecs").describe_services, cluster=cluster, services=names
        )
        obs.result["data"] = [normalize.ecs_health(row) for row in response.get("services", [])]
        obs.result["pagination_complete"] = True
        returned = {row["name"] for row in obs.result["data"]}
        obs.result["missing_resource_ids"] = [name for name in names if name not in returned]
        for failure in response.get("failures", []):
            code = failure.get("reason", "ServiceFailure")
            if code not in {"MISSING", "ACCESS_DENIED"}:
                code = "ServiceFailure"
            obs.error(code, "ecs", "DescribeServices", resource_id=failure.get("arn"),
                      kind="access_denied" if code == "ACCESS_DENIED" else "api_error")
        if any(row["deployments_truncated"] for row in obs.result["data"]):
            obs.result["truncated"] = True

    def _lambda_functions(self, obs):
        obs.result["scope"]["function_kind"] = "event"
        self.paginate(
            obs, "lambda", "ListFunctions", self.client("lambda").list_functions,
            {"MaxItems": min(50, self.settings.max_resources)},
            lambda r: r.get("Functions", []), normalize.lambda_function, "Marker", "NextMarker",
        )

    def _lambda_health(self, obs, function_name):
        function_name = self.identifier(function_name, "lambda", "function")
        obs.result["scope"]["function_kind"] = "event"
        response = self.call(
            obs, "lambda", "GetFunctionConfiguration", self.client("lambda").get_function_configuration,
            FunctionName=function_name,
        )
        obs.result["data"] = [normalize.lambda_function(response, configuration=True)]
        obs.result["pagination_complete"] = True

    def _metrics(self, obs, service, resource_id, start_time, end_time):
        from .metrics import collect_metrics
        collect_metrics(self, obs, service, resource_id, start_time, end_time)

    def _alarms(self, obs, state):
        params = {"AlarmTypes": ["MetricAlarm", "CompositeAlarm"], "MaxRecords": min(50, self.settings.max_resources)}
        if state != "ALL":
            params["StateValue"] = state
        obs.result["scope"]["alarm_state"] = state
        self.paginate(
            obs, "cloudwatch", "DescribeAlarms", self.client("cloudwatch").describe_alarms, params,
            lambda r: [
                {**row, "_alarm_type": kind}
                for key, kind in [("MetricAlarms", "metric"), ("CompositeAlarms", "composite")]
                for row in r.get(key, [])
            ],
            normalize.alarm, "NextToken", "NextToken",
        )
