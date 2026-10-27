from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import config_inventory, network_inventory


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


Identifier = Annotated[str, Field(min_length=1, max_length=256)]
InstanceId = Annotated[str, Field(pattern=r"^i-(?:[0-9a-f]{8}|[0-9a-f]{17})$")]


class InstanceHealthArgs(Arguments):
    instance_ids: Annotated[list[InstanceId], Field(min_length=1, max_length=20)]


class ClusterArgs(Arguments):
    cluster: Identifier


class ServiceHealthArgs(ClusterArgs):
    services: Annotated[list[Identifier], Field(min_length=1, max_length=10)]


class FunctionArgs(Arguments):
    function_name: Identifier


class MetricArgs(Arguments):
    service: Annotated[str, Field(min_length=1, max_length=32)]
    resource_id: Identifier
    start_time: Annotated[str, Field(min_length=10, max_length=40)]
    end_time: Annotated[str, Field(min_length=10, max_length=40)]


class AlarmArgs(Arguments):
    state: Literal["ALARM", "OK", "INSUFFICIENT_DATA", "ALL"] = "ALARM"


# Model input never selects an SDK operation or a shell command.
TOOL_SCHEMAS = {
    "get_account_context": ("sts", Arguments, "Verify the execution account, fixed Regions, and supported scope."),
    "list_ec2_instances": ("ec2", Arguments, "List bounded EC2 configuration states. Does not assess application health."),
    "get_ec2_instance_health": ("ec2", InstanceHealthArgs, "Read EC2 instance, system, and attached EBS status checks."),
    "list_rds_instances": ("rds", Arguments, "List RDS DB instance configuration states, without database contents."),
    "list_ecs_clusters": ("ecs", Arguments, "Discover a bounded list of ECS cluster ARNs."),
    "list_ecs_services": ("ecs", ClusterArgs, "List bounded service ARNs in one verified-account ECS cluster."),
    "get_ecs_service_health": ("ecs", ServiceHealthArgs, "Read desired/running/pending task counts and deployment states."),
    "list_lambda_functions": ("lambda", Arguments, "List Lambda Event Functions only, excluding Web Functions and secrets."),
    "get_lambda_function_health": ("lambda", FunctionArgs, "Read one Event Function's configuration state; no environment variables."),
    "get_resource_metrics": ("cloudwatch", MetricArgs, "Read allowlisted EC2/RDS/ECS/Lambda metrics; missing data remains unknown."),
    "list_cloudwatch_alarms": ("cloudwatch", AlarmArgs, "List metric and composite alarms in a specified state."),
    **network_inventory.TOOL_SCHEMAS,
    **config_inventory.TOOL_SCHEMAS,
}
