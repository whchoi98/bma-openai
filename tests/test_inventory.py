import json
from datetime import timedelta

import pytest
from conftest import ACCOUNT, NOW

EC2_ID = "i-0123456789abcdef0"
EC2_ID2 = "i-0123456789abcdef1"
CLUSTER = f"arn:aws:ecs:ap-northeast-2:{ACCOUNT}:cluster/demo"
SERVICE = f"arn:aws:ecs:ap-northeast-2:{ACCOUNT}:service/demo/api"


def assert_metadata(result, service):
    assert result["account_id"] == ACCOUNT
    assert result["region"] == "ap-northeast-2"
    assert result["service"] == service
    assert result["observed_at"] == "2026-10-26T12:00:00Z"
    assert isinstance(result["api_calls"], list)
    assert isinstance(result["resource_ids"], list)
    assert isinstance(result["pagination_complete"], bool)
    assert isinstance(result["truncated"], bool)
    assert isinstance(result["errors"], list)
    assert isinstance(result["permission_denied"], bool)
    assert result["duration_ms"] >= 0
    assert result["mode"] == "live"


def test_region_is_explicit_even_when_aws_region_is_different(monkeypatch, aws):
    from aws_inventory.config import Settings
    from aws_inventory.engine import AwsInventory

    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.setenv("EXPECTED_ACCOUNT_ID", ACCOUNT)
    aws.identity()
    engine = AwsInventory(Settings.from_env(), session=aws)
    engine.client("ec2")
    aws.stub("ec2").add_response("describe_instances", {"Reservations": []}, {"MaxResults": 50})
    engine.invoke("list_ec2_instances")
    assert set(aws.regions) == {("sts", "us-east-1"), ("ec2", "ap-northeast-2")}
    assert engine.client("ec2").meta.config.retries["total_max_attempts"] == 3


def test_mismatched_account_blocks_resource_calls(aws):
    from aws_inventory.config import Settings
    from aws_inventory.engine import AwsInventory

    aws.identity("999988887777")
    engine = AwsInventory(Settings(expected_account_id=ACCOUNT), session=aws)
    result = engine.invoke("list_ec2_instances")
    assert result["status"] == "account_mismatch"
    assert result["account_id"] == "999988887777"
    assert result["data"] == []
    assert all(service == "sts" for service, _ in aws.regions)
    assert result["pagination_complete"] is False


def test_sts_failure_blocks_queries(aws):
    from aws_inventory.config import Settings
    from aws_inventory.engine import AwsInventory

    aws.stub("sts").add_client_error("get_caller_identity", "ExpiredToken")
    result = AwsInventory(Settings(expected_account_id=ACCOUNT), session=aws).invoke("list_rds_instances")
    assert result["status"] == "api_error"
    assert result["account_id"] is None
    assert all(service == "sts" for service, _ in aws.regions)


@pytest.mark.parametrize("value", ["", "123", "not-an-account"])
def test_live_requires_deployment_account(value):
    from aws_inventory.config import Settings

    with pytest.raises(ValueError):
        Settings(expected_account_id=value)


def test_free_form_account_and_region_are_not_tool_parameters(inventory, aws):
    result = inventory.invoke(
        "list_ec2_instances", {"account_id": "999988887777", "region": "us-east-1"}
    )
    assert result["status"] == "invalid_input"
    assert result["data"] == []
    assert all(service == "sts" for service, _ in aws.regions)


def test_account_context_is_verified(inventory):
    result = inventory.invoke("get_account_context")
    assert_metadata(result, "sts")
    assert result["status"] == "ok"
    assert result["data"][0]["account_verified"] is True
    assert result["data"][0]["app_region"] == "us-east-1"
    assert set(result["data"][0]["supported_services"]) == {"ec2", "rds", "ecs", "lambda", "cloudwatch", "vpc", "ebs", "ecr", "s3", "dynamodb", "elasticache", "opensearch", "msk"}


def test_empty_inventory_is_successful_empty(inventory, aws):
    aws.stub("ec2").add_response("describe_instances", {"Reservations": []}, {"MaxResults": 50})
    result = inventory.invoke("list_ec2_instances")
    assert_metadata(result, "ec2")
    assert result["status"] == "empty"
    assert result["data"] == []
    assert result["pagination_complete"] is True
    assert result["truncated"] is False
    assert result["errors"] == []


def test_access_denied_is_not_empty(inventory, aws):
    aws.stub("rds").add_client_error(
        "describe_db_instances", "AccessDenied", "sensitive text", expected_params={"MaxRecords": 50}
    )
    result = inventory.invoke("list_rds_instances")
    assert_metadata(result, "rds")
    assert result["status"] == "access_denied"
    assert result["permission_denied"] is True
    assert result["pagination_complete"] is False
    assert "sensitive text" not in json.dumps(result)
    assert result["api_calls"][-1]["api"] == "DescribeDBInstances"


def test_ec2_follows_tokens_and_normalizes(inventory, aws):
    aws.stub("ec2").add_response(
        "describe_instances",
        {
            "Reservations": [{"Instances": [{"InstanceId": EC2_ID, "State": {"Name": "running"},
                                            "PrivateIpAddress": "10.0.0.1",
                                            "Tags": [{"Key": "secret", "Value": "do-not-return"}]}]}],
            "NextToken": "page-two",
        },
        {"MaxResults": 50},
    )
    aws.stub("ec2").add_response(
        "describe_instances",
        {"Reservations": [{"Instances": [{"InstanceId": EC2_ID2, "State": {"Name": "stopped"}}]}]},
        {"MaxResults": 50, "NextToken": "page-two"},
    )
    result = inventory.invoke("list_ec2_instances")
    assert result["count"] == 2
    assert result["pagination_complete"] is True
    assert result["resource_ids"] == [EC2_ID, EC2_ID2]
    assert result["data"][0]["application_health"] == "not_assessed"
    assert "do-not-return" not in json.dumps(result)
    assert "10.0.0.1" not in json.dumps(result)
    aws.stub("ec2").assert_no_pending_responses()


def test_cap_inside_nested_ec2_reservations_marks_truncation(aws):
    from aws_inventory.config import Settings
    from aws_inventory.engine import AwsInventory

    aws.identity()
    aws.stub("ec2").add_response(
        "describe_instances",
        {"Reservations": [{"Instances": [{"InstanceId": EC2_ID}, {"InstanceId": EC2_ID2}]}]},
        {"MaxResults": 5},
    )
    result = AwsInventory(Settings(expected_account_id=ACCOUNT, max_resources=1), session=aws).invoke(
        "list_ec2_instances"
    )
    assert result["count"] == 1
    assert result["truncated"] is True
    assert result["pagination_complete"] is False
    assert result["status"] == "partial"


def test_exact_cap_without_more_data_is_complete(aws):
    from aws_inventory.config import Settings
    from aws_inventory.engine import AwsInventory

    aws.identity()
    aws.stub("ec2").add_response(
        "describe_instances", {"Reservations": [{"Instances": [{"InstanceId": EC2_ID}]}]},
        {"MaxResults": 5},
    )
    result = AwsInventory(Settings(expected_account_id=ACCOUNT, max_resources=1), session=aws).invoke(
        "list_ec2_instances"
    )
    assert result["truncated"] is False
    assert result["pagination_complete"] is True
    assert result["status"] == "ok"


def test_page_failure_preserves_evidence(inventory, aws):
    aws.stub("rds").add_response(
        "describe_db_instances",
        {"DBInstances": [{"DBInstanceIdentifier": "db-one", "DBInstanceStatus": "available"}],
         "Marker": "more"},
        {"MaxRecords": 50},
    )
    aws.stub("rds").add_client_error(
        "describe_db_instances", "ThrottlingException", expected_params={"MaxRecords": 50, "Marker": "more"}
    )
    result = inventory.invoke("list_rds_instances")
    assert result["status"] == "partial"
    assert result["count"] == 1
    assert result["pagination_complete"] is False
    assert result["truncated"] is False
    assert result["errors"][0]["code"] == "ThrottlingException"
    assert result["data"][0]["application_health"] == "not_assessed"


def test_repeated_tokens_terminate(inventory, aws):
    for expected in [{"MaxRecords": 50}, {"MaxRecords": 50, "Marker": "loop"}]:
        aws.stub("rds").add_response("describe_db_instances", {"DBInstances": [], "Marker": "loop"}, expected)
    result = inventory.invoke("list_rds_instances")
    assert result["pagination_complete"] is False
    assert result["errors"][0]["code"] == "RepeatedPaginationToken"
    aws.stub("rds").assert_no_pending_responses()


def test_ec2_health_includes_stopped_and_missing_are_unknown(inventory, aws):
    aws.stub("ec2").add_response(
        "describe_instance_status",
        {"InstanceStatuses": [{"InstanceId": EC2_ID, "InstanceState": {"Name": "running"},
                              "InstanceStatus": {"Status": "impaired"},
                              "SystemStatus": {"Status": "ok"}}]},
        {"InstanceIds": [EC2_ID, EC2_ID2], "IncludeAllInstances": True},
    )
    result = inventory.invoke("get_ec2_instance_health", {"instance_ids": [EC2_ID, EC2_ID2]})
    assert result["status"] == "partial"
    assert result["data"][0]["instance_status"] == "impaired"
    assert result["data"][0]["application_health"] == "not_assessed"
    assert result["missing_resource_ids"] == [EC2_ID2]
    assert result["count"] == 1


def test_rds_does_not_return_credentials_or_endpoint(inventory, aws):
    aws.stub("rds").add_response(
        "describe_db_instances",
        {"DBInstances": [{"DBInstanceIdentifier": "payments", "DBInstanceStatus": "available",
                          "MasterUsername": "private-user",
                          "Endpoint": {"Address": "private-db", "Port": 5432},
                          "MasterUserSecret": {"SecretArn": f"arn:aws:secretsmanager:ap-northeast-2:{ACCOUNT}:secret:test"}}]},
        {"MaxRecords": 50},
    )
    result = inventory.invoke("list_rds_instances")
    assert result["data"][0]["state"] == "available"
    assert "private-" not in json.dumps(result)
    assert "SecretArn" not in json.dumps(result)


def test_ecs_clusters_and_services_are_separate_scopes(inventory, aws):
    aws.stub("ecs").add_response("list_clusters", {"clusterArns": [CLUSTER]}, {"maxResults": 50})
    result = inventory.invoke("list_ecs_clusters")
    assert result["data"][0]["id"] == CLUSTER
    aws.identity()
    aws.stub("ecs").add_response(
        "list_services", {"serviceArns": [SERVICE]}, {"cluster": "demo", "maxResults": 50}
    )
    result = inventory.invoke("list_ecs_services", {"cluster": "demo"})
    assert result["data"][0]["id"] == SERVICE
    assert result["scope"]["cluster"] == "demo"


def test_ecs_service_failure_does_not_hide_success(inventory, aws):
    aws.stub("ecs").add_response(
        "describe_services",
        {
            "services": [{
                "serviceArn": SERVICE, "serviceName": "api", "clusterArn": CLUSTER,
                "status": "ACTIVE", "desiredCount": 2, "runningCount": 1, "pendingCount": 1,
                "deployments": [{"id": "ecs-svc/1", "status": "PRIMARY", "rolloutState": "IN_PROGRESS",
                                 "desiredCount": 2, "runningCount": 1, "pendingCount": 1}],
                "events": [{"message": "DO_NOT_LEAK"}],
            }],
            "failures": [{"arn": "absent", "reason": "MISSING", "detail": "DO_NOT_LEAK"}],
        },
        {"cluster": "demo", "services": ["api", "absent"]},
    )
    result = inventory.invoke("get_ecs_service_health", {"cluster": "demo", "services": ["api", "absent"]})
    assert result["status"] == "partial"
    assert result["count"] == 1
    assert result["data"][0]["running_count"] == 1
    assert result["data"][0]["deployments"][0]["rollout_state"] == "IN_PROGRESS"
    assert "DO_NOT_LEAK" not in json.dumps(result)


def test_all_ecs_services_denied_is_access_denied(inventory, aws):
    aws.stub("ecs").add_response(
        "describe_services", {"services": [], "failures": [{"arn": "api", "reason": "ACCESS_DENIED"}]},
        {"cluster": "demo", "services": ["api"]},
    )
    result = inventory.invoke("get_ecs_service_health", {"cluster": "demo", "services": ["api"]})
    assert result["status"] == "access_denied"
    assert result["permission_denied"] is True


def test_foreign_arn_is_rejected_before_regional_call(inventory, aws):
    result = inventory.invoke("list_ecs_services", {"cluster": "arn:aws:ecs:us-east-1:999988887777:cluster/x"})
    assert result["status"] == "invalid_input"
    assert all(service == "sts" for service, _ in aws.regions)


def test_lambda_is_event_api_and_secrets_are_stripped(inventory, aws):
    aws.stub("lambda").add_response(
        "list_functions",
        {"Functions": [{
            "FunctionName": "demo", "FunctionArn": f"arn:aws:lambda:ap-northeast-2:{ACCOUNT}:function:demo",
            "Runtime": "python3.12", "Environment": {"Variables": {"PASSWORD": "never-return"}},
            "Role": f"arn:aws:iam::{ACCOUNT}:role/private-role", "KMSKeyArn": "private-kms",
        }]},
        {"MaxItems": 50},
    )
    result = inventory.invoke("list_lambda_functions")
    assert result["api_calls"][-1]["api"] == "ListFunctions"
    assert result["data"][0]["function_kind"] == "event"
    assert result["data"][0]["state"] is None
    assert "never-return" not in json.dumps(result)
    assert "private-" not in json.dumps(result)
    assert "lambda-web" not in [name for name, _ in aws.regions]


def test_lambda_configuration_health_is_separate_and_allowlisted(inventory, aws):
    aws.stub("lambda").add_response(
        "get_function_configuration",
        {"FunctionName": "demo", "State": "Active", "LastUpdateStatus": "Successful",
         "Environment": {"Variables": {"PASSWORD": "secret-value"}},
         "StateReason": "potential-private-value"},
        {"FunctionName": "demo"},
    )
    result = inventory.invoke("get_lambda_function_health", {"function_name": "demo"})
    assert result["data"][0]["state"] == "Active"
    assert result["data"][0]["application_health"] == "not_assessed"
    assert "secret-value" not in json.dumps(result)
    assert "potential-private-value" not in json.dumps(result)


def metrics_args(**overrides):
    return {
        "service": "lambda", "resource_id": "demo",
        "start_time": (NOW - timedelta(hours=1)).isoformat(), "end_time": NOW.isoformat(),
        **overrides,
    }


def metrics_params():
    return {
        "MetricDataQueries": [
            {"Id": f"m{i}", "MetricStat": {"Metric": {"Namespace": "AWS/Lambda", "MetricName": name,
             "Dimensions": [{"Name": "FunctionName", "Value": "demo"}]},
             "Period": 300, "Stat": stat}, "ReturnData": True}
            for i, (name, stat) in enumerate([
                ("Invocations", "Sum"), ("Errors", "Sum"), ("Throttles", "Sum"), ("Duration", "Average")
            ])
        ],
        "StartTime": NOW - timedelta(hours=1), "EndTime": NOW,
        "ScanBy": "TimestampAscending", "MaxDatapoints": 1440,
    }


def test_no_cloudwatch_data_stays_missing(inventory, aws):
    aws.stub("cloudwatch").add_response(
        "get_metric_data",
        {"MetricDataResults": [{"Id": f"m{i}", "Values": [], "Timestamps": [], "StatusCode": "Complete"}
                               for i in range(4)]},
        metrics_params(),
    )
    result = inventory.invoke("get_resource_metrics", metrics_args())
    assert_metadata(result, "lambda")
    assert result["status"] == "empty"
    assert result["datapoint_count"] == 0
    assert all(metric["data_status"] == "no_data" and metric["points"] == [] for metric in result["data"])
    assert result["pagination_complete"] is True


def test_real_zero_datapoint_is_distinct_from_absence(inventory, aws):
    rows = [{"Id": f"m{i}", "Values": [], "Timestamps": [], "StatusCode": "Complete"} for i in range(4)]
    rows[1].update(Values=[0.0], Timestamps=[NOW - timedelta(minutes=5)])
    aws.stub("cloudwatch").add_response("get_metric_data", {"MetricDataResults": rows}, metrics_params())
    result = inventory.invoke("get_resource_metrics", metrics_args())
    assert result["status"] == "ok"
    assert result["data"][1]["points"][0]["value"] == 0.0
    assert result["data"][0]["data_status"] == "no_data"


def test_metric_api_partial_data_is_not_healthy(inventory, aws):
    rows = [{"Id": f"m{i}", "Values": [], "Timestamps": [], "StatusCode": "Complete"} for i in range(4)]
    rows[1].update(Values=[2.0], Timestamps=[NOW - timedelta(minutes=5)], StatusCode="PartialData")
    aws.stub("cloudwatch").add_response("get_metric_data", {"MetricDataResults": rows}, metrics_params())
    result = inventory.invoke("get_resource_metrics", metrics_args())
    assert result["status"] == "partial"
    assert result["data"][1]["data_status"] == "partial"
    assert result["errors"]


@pytest.mark.parametrize("rows", [
    [{"Id": f"m{i}", "StatusCode": "InternalError", "Values": [], "Timestamps": []} for i in range(4)],
    [],
])
def test_all_metric_results_failed_is_api_error(inventory, aws, rows):
    aws.stub("cloudwatch").add_response("get_metric_data", {"MetricDataResults": rows}, metrics_params())
    result = inventory.invoke("get_resource_metrics", metrics_args())
    assert result["status"] == "api_error"
    assert result["datapoint_count"] == 0


def test_incomplete_metric_pagination_does_not_claim_complete_series(inventory, aws):
    rows = [{"Id": f"m{i}", "Values": [], "Timestamps": [], "StatusCode": "Complete"} for i in range(4)]
    rows[0].update(Values=[1.0], Timestamps=[NOW - timedelta(minutes=5)])
    aws.stub("cloudwatch").add_response("get_metric_data", {"MetricDataResults": rows, "NextToken": "next"}, metrics_params())
    aws.stub("cloudwatch").add_client_error("get_metric_data", "AccessDenied", expected_params={**metrics_params(), "NextToken": "next"})
    result = inventory.invoke("get_resource_metrics", metrics_args())
    assert result["status"] == "partial"
    assert result["data"][0]["data_status"] == "partial"
    assert result["data"][1]["data_status"] == "unknown"


def test_metrics_tokens_are_followed(inventory, aws):
    rows = [{"Id": f"m{i}", "Values": [], "Timestamps": [], "StatusCode": "Complete"} for i in range(4)]
    rows[0].update(Values=[1.0], Timestamps=[NOW - timedelta(minutes=10)], StatusCode="PartialData")
    aws.stub("cloudwatch").add_response(
        "get_metric_data", {"MetricDataResults": rows, "NextToken": "metric-next"}, metrics_params()
    )
    rows2 = [{"Id": f"m{i}", "Values": [], "Timestamps": [], "StatusCode": "Complete"} for i in range(4)]
    rows2[0].update(Values=[2.0], Timestamps=[NOW - timedelta(minutes=5)])
    aws.stub("cloudwatch").add_response(
        "get_metric_data", {"MetricDataResults": rows2}, {**metrics_params(), "NextToken": "metric-next"}
    )
    result = inventory.invoke("get_resource_metrics", metrics_args())
    assert result["status"] == "ok"
    assert result["pagination_complete"] is True
    assert len(result["data"][0]["points"]) == 2


@pytest.mark.parametrize("overrides", [
    {"start_time": "2026-10-26T11:00:00"},
    {"end_time": (NOW - timedelta(hours=2)).isoformat()},
    {"start_time": (NOW - timedelta(hours=7)).isoformat()},
    {"end_time": (NOW + timedelta(hours=1)).isoformat()},
    {"resource_id": "arn:aws:lambda:us-east-1:999988887777:function:foreign"},
])
def test_invalid_metric_scope_makes_no_cloudwatch_call(inventory, aws, overrides):
    result = inventory.invoke("get_resource_metrics", metrics_args(**overrides))
    assert result["status"] == "invalid_input"
    assert all(service == "sts" for service, _ in aws.regions)


def test_unsupported_service_is_explicit(inventory, aws):
    result = inventory.invoke("get_resource_metrics", metrics_args(service="s3"))
    assert result["status"] == "unsupported_service"
    assert all(service == "sts" for service, _ in aws.regions)


def test_alarms_include_both_types_without_actions(inventory, aws):
    aws.stub("cloudwatch").add_response(
        "describe_alarms",
        {"MetricAlarms": [{"AlarmName": "Errors", "AlarmArn": f"arn:aws:cloudwatch:ap-northeast-2:{ACCOUNT}:alarm:Errors",
                           "StateValue": "ALARM", "AlarmActions": ["private-action"], "StateReason": "private-reason"}],
         "CompositeAlarms": [{"AlarmName": "Combined", "StateValue": "ALARM"}]},
        {"StateValue": "ALARM", "AlarmTypes": ["MetricAlarm", "CompositeAlarm"], "MaxRecords": 50},
    )
    result = inventory.invoke("list_cloudwatch_alarms", {"state": "ALARM"})
    assert result["count"] == 2
    assert result["data"][1]["alarm_type"] == "composite"
    assert "private-" not in json.dumps(result)


def test_partial_service_failure_does_not_poison_later_queries(inventory, aws):
    aws.stub("ec2").add_client_error("describe_instances", "UnauthorizedOperation", expected_params={"MaxResults": 50})
    first = inventory.invoke("list_ec2_instances")
    aws.identity()
    aws.stub("rds").add_response("describe_db_instances", {"DBInstances": []}, {"MaxRecords": 50})
    second = inventory.invoke("list_rds_instances")
    assert first["status"] == "access_denied"
    assert second["status"] == "empty"
    aws.stub("sts").assert_no_pending_responses()


@pytest.mark.parametrize("name,args", [
    ("execute_aws_cli", {"command": "aws ec2 stop-instances"}),
    ("execute_boto3", {"operation": "stop_instances"}),
    ("get_ec2_instance_health", {"instance_ids": []}),
    ("get_ec2_instance_health", {"instance_ids": [EC2_ID] * 21}),
    ("get_ecs_service_health", {"cluster": "demo", "services": ["x"] * 11}),
])
def test_only_bounded_implemented_tools_are_accepted(inventory, name, args):
    assert inventory.invoke(name, args)["status"] == "invalid_input"
