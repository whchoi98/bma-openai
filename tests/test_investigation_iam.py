"""Evaluate the investigation trust/storage boundaries against concrete requests."""
import fnmatch
import re
from pathlib import Path

import pytest
import yaml

ACCOUNT = "111122223333"
REGION = "us-east-1"
WORKER = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:bma-seoul-inventory-investigation-worker"
VALUES = {
    "AgentBackend": "bma", "AWS::NoValue": None, "AWS::Partition": "aws",
    "AWS::AccountId": ACCOUNT, "AWS::Region": REGION, "AppRegion": REGION,
    "TargetRegion": "ap-northeast-2", "RuntimeName": "bma_seoul_inventory",
    "RuntimeRepositoryName": "bma-seoul-runtime", "BmaModel": "openai.gpt-6-luna",
    "ConverseModel": "global.openai.gpt-6-luna", "AWS::StackName": "bma-seoul-inventory",
    "WebEndpoint.DomainName": "example.lambda-web.us-east-1.on.aws",
    "WebDistribution.DomainName": "example.cloudfront.net",
    "MaxResources": "2", "MaxPages": "2", "MaxMetricHours": "1",
    "MaxDatapoints": "100", "MaxTurnSeconds": "300",
    "Runtime.AgentRuntimeArn": f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:runtime/demo",
    "SessionRole.Arn": f"arn:aws:iam::{ACCOUNT}:role/BmaSession",
    "InvestigationWorker.Arn": WORKER,
    "WorkerRole.Arn": f"arn:aws:iam::{ACCOUNT}:role/Worker",
    "AppState.Arn": "arn:aws:s3:::app-state", "AppState": "app-state",
    "WorkerLogs.Arn": f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:worker:*",
    "WebLogs.Arn": f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:web:*",
    "CodeBucket.Arn": "arn:aws:s3:::code-bucket",
    "WebFunctionName": "bma-seoul-inventory-web",
    "InvestigationWorkerFunctionName": "bma-seoul-inventory-investigation-worker",
}
TEMPLATE = Path(__file__).resolve().parents[1] / "infra/template.yaml"


class Loader(yaml.SafeLoader):
    pass


def intrinsic(loader, tag, node):
    if tag == "If":
        _, yes, no = loader.construct_sequence(node, deep=True)
        return yes if VALUES["AgentBackend"] == "converse" else no
    if tag == "Ref":
        name = loader.construct_scalar(node)
        return VALUES.get(name, name)
    if tag in {"Sub", "GetAtt"}:
        text = loader.construct_scalar(node)
        return VALUES.get(text, text) if tag == "GetAtt" else re.sub(r"\$\{([^}]+)\}", lambda m: VALUES[m[1]], text)
    return loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode) else loader.construct_scalar(node)


Loader.add_multi_constructor("!", intrinsic)


def resources():
    return yaml.load(TEMPLATE.read_text(), Loader=Loader)["Resources"]


def allowed(role, action, resource, **context):
    data = resources()
    if role not in data:
        return False
    for policy in data[role]["Properties"]["Policies"]:
        for statement in policy["PolicyDocument"]["Statement"]:
            if not statement or statement["Effect"] != "Allow":
                continue
            actions = statement["Action"]
            arns = statement["Resource"]
            actions = actions if isinstance(actions, list) else [actions]
            arns = arns if isinstance(arns, list) else [arns]
            if not any(fnmatch.fnmatchcase(action, item) for item in actions):
                continue
            if not any(fnmatch.fnmatchcase(resource, item) for item in arns):
                continue
            matches = True
            for operator, conditions in statement.get("Condition", {}).items():
                for key, choices in conditions.items():
                    choices = choices if isinstance(choices, list) else [choices]
                    value = context.get(key)
                    if operator == "StringEquals":
                        matches &= value in choices
                    elif operator == "StringLike":
                        matches &= isinstance(value, str) and any(fnmatch.fnmatchcase(value, item) for item in choices)
                    elif operator == "NumericLessThanEquals":
                        try:
                            matches &= value is not None and any(float(value) <= float(item) for item in choices)
                        except (TypeError, ValueError):
                            matches = False
                    else:
                        matches = False
            if matches:
                return True
    return False


def test_web_dispatches_only_designated_worker():
    assert allowed("WebRole", "lambda:InvokeFunction", WORKER)
    for arn in [WORKER + "-other", WORKER.replace(REGION, "ap-northeast-2"), WORKER.replace(ACCOUNT, "999988887777")]:
        assert not allowed("WebRole", "lambda:InvokeFunction", arn)
    assert not allowed("WorkerRole", "lambda:InvokeFunction", WORKER)
    assert not allowed("WebRole", "bedrock-mantle:GetAgentSession",
                       f"arn:aws:bedrock-mantle:{REGION}:{ACCOUNT}:project/default")


def test_deployment_outputs_identify_the_worker_function_and_role():
    outputs = yaml.load(TEMPLATE.read_text(), Loader=Loader)["Outputs"]
    assert outputs.get("InvestigationWorkerArn", {}).get("Value") == WORKER
    assert outputs.get("WorkerRoleArn", {}).get("Value") == VALUES["WorkerRole.Arn"]


@pytest.mark.parametrize("action", [
    "CreateAgentSession", "GetAgentSession", "ListAgentSessions", "CreateAgentSessionEvent",
    "ListAgentSessionEvents", "ListAgentSessionItems",
])
def test_worker_session_apis_stay_in_same_account_and_app_region(action):
    arn = f"arn:aws:bedrock-mantle:{REGION}:{ACCOUNT}:project/default"
    assert allowed("WorkerRole", "bedrock-mantle:" + action, arn)
    assert not allowed("WorkerRole", "bedrock-mantle:" + action, arn.replace(ACCOUNT, "999988887777"))
    assert not allowed("WorkerRole", "bedrock-mantle:" + action, arn.replace(REGION, "ap-northeast-2"))


def test_worker_can_only_pass_designated_session_role_to_bma():
    arn = VALUES["SessionRole.Arn"]
    assert allowed("WorkerRole", "iam:PassRole", arn, **{"iam:PassedToService": "bedrock-mantle.amazonaws.com"})
    assert not allowed("WorkerRole", "iam:PassRole", arn + "-other", **{"iam:PassedToService": "bedrock-mantle.amazonaws.com"})
    assert not allowed("WorkerRole", "iam:PassRole", arn, **{"iam:PassedToService": "lambda.amazonaws.com"})


@pytest.mark.parametrize("action", [
    "ec2:DescribeInstances", "rds:DescribeDBInstances", "cloudwatch:DescribeAlarms",
    "bedrock-mantle:CreateInference", "bedrock:InvokeModelWithResponseStream",
    "bedrock-agentcore:InvokeAgentRuntime", "sts:AssumeRole",
])
def test_worker_does_not_gain_direct_queries_models_or_role_assumption(action):
    for arn in ["*", VALUES["Runtime.AgentRuntimeArn"], VALUES["SessionRole.Arn"],
                f"arn:aws:rds:ap-northeast-2:{ACCOUNT}:db:orders"]:
        assert not allowed("WorkerRole", action, arn)


@pytest.mark.parametrize("role", ["WebRole", "WorkerRole"])
def test_investigation_records_and_lists_stay_in_fixed_namespace(role):
    prefix = f"investigations/{ACCOUNT}/ap-northeast-2/"
    for category in ["sessions", "turns", "index"]:
        arn = "arn:aws:s3:::app-state/" + prefix + category + "/record.json"
        for action in ["s3:GetObject", "s3:PutObject"]:
            assert allowed(role, action, arn)
            assert not allowed(role, action, arn.replace(ACCOUNT, "999988887777"))
            assert not allowed(role, action, arn.replace("ap-northeast-2", REGION))
        assert not allowed(role, "s3:DeleteObject", arn)
    assert allowed(role, "s3:ListBucket", "arn:aws:s3:::app-state", **{"s3:prefix": prefix + "index/"})
    for attempted in ["", "runs/", prefix, prefix + "sessions/", prefix + "index/../"]:
        assert not allowed(role, "s3:ListBucket", "arn:aws:s3:::app-state", **{"s3:prefix": attempted})
    assert not allowed(role, "s3:GetObject", "arn:aws:s3:::another-bucket/" + prefix + "turns/record.json")


def test_worker_writes_existing_reports_and_only_own_logs():
    assert allowed("WorkerRole", "sts:GetCallerIdentity", "*")
    for suffix in ["runs/run.json", f"history/{ACCOUNT}/ap-northeast-2/index.json"]:
        for action in ["s3:GetObject", "s3:PutObject"]:
            assert allowed("WorkerRole", action, "arn:aws:s3:::app-state/" + suffix)
    assert allowed("WorkerRole", "logs:PutLogEvents", VALUES["WorkerLogs.Arn"].replace("*", "stream"))
    assert not allowed("WorkerRole", "logs:PutLogEvents", VALUES["WebLogs.Arn"].replace("*", "stream"))


@pytest.mark.parametrize("role", ["WebRole", "WorkerRole"])
def test_missing_object_probe_lists_only_one_exact_key_in_fixed_namespaces(role):
    uuid = "11111111-2222-4333-8444-555555555555"
    prefix = f"investigations/{ACCOUNT}/ap-northeast-2/"
    keys = [f"runs/{uuid}.json", f"{prefix}sessions/{uuid}.json",
            f"{prefix}turns/{uuid}.json", f"{prefix}index/8227798399999-{uuid}.json"]
    for key in keys:
        assert allowed(role, "s3:ListBucket", "arn:aws:s3:::app-state",
                       **{"s3:prefix": key, "s3:max-keys": 1})
        for size in [2, 20, 1000, None]:
            assert not allowed(role, "s3:ListBucket", "arn:aws:s3:::app-state",
                               **{"s3:prefix": key, "s3:max-keys": size})
    for key in [f"{prefix}sessions/", f"{prefix}turns/{uuid}", f"{prefix}index/{uuid}.json",
                f"{prefix}sessions/{uuid}.json/extra", f"runs/{uuid}.json/extra",
                f"investigations/999988887777/ap-northeast-2/turns/{uuid}.json",
                f"investigations/{ACCOUNT}/us-east-1/turns/{uuid}.json"]:
        assert not allowed(role, "s3:ListBucket", "arn:aws:s3:::app-state",
                           **{"s3:prefix": key, "s3:max-keys": 1})
    assert not allowed(role, "s3:ListBucket", "arn:aws:s3:::other-state",
                       **{"s3:prefix": keys[0], "s3:max-keys": 1})


def test_worker_is_bounded_uses_existing_zip_and_has_no_browser_secret():
    data = resources()
    assert "InvestigationWorker" in data
    worker = data["InvestigationWorker"]["Properties"]
    assert worker["Runtime"] == "nodejs24.x"
    assert worker["Architectures"] == ["arm64"]
    assert worker["Handler"] == "investigation-worker.handler"
    assert worker["MemorySize"] == 512
    assert worker["Timeout"] == 360
    assert worker["ReservedConcurrentExecutions"] == 2
    assert worker["Code"] == {"S3Bucket": "CodeBucket", "S3Key": "CodeKey", "S3ObjectVersion": "CodeVersionId"}
    assert "APP_ACCESS_TOKEN" not in worker["Environment"]["Variables"]
    assert worker["Environment"]["Variables"]["MAX_TURN_SECONDS"] == "300"
    web = data["WebRevision"]["Properties"]["ServiceConfig"]["EnvironmentVariables"]
    assert web["INVESTIGATION_WORKER_ARN"] == WORKER
    for key in ["APP_REGION", "TARGET_REGION", "EXPECTED_ACCOUNT_ID", "BMA_MODEL", "BMA_RUNTIME_ARN",
                "BMA_SESSION_ROLE_ARN", "APP_STATE_BUCKET", "MAX_RESOURCES", "MAX_PAGES", "MAX_METRIC_HOURS", "MAX_DATAPOINTS"]:
        assert worker["Environment"]["Variables"][key] == web[key]
    configs = [item["Properties"] for item in data.values() if item["Type"] == "AWS::Lambda::EventInvokeConfig"]
    assert len(configs) == 1
    assert configs[0]["MaximumRetryAttempts"] == 1
    assert configs[0]["MaximumEventAgeInSeconds"] == 600


def test_investigations_expire_including_noncurrent_versions():
    rules = resources()["AppState"]["Properties"]["LifecycleConfiguration"]["Rules"]
    rule = next((item for item in rules if item["Prefix"] == "investigations/"), None)
    assert rule is not None
    assert rule["Status"] == "Enabled"
    assert rule["ExpirationInDays"] == 7
    assert rule["NoncurrentVersionExpiration"] == {"NoncurrentDays": 1}


def test_bootstrap_code_read_is_scoped_to_exact_worker_function():
    statements = yaml.load(TEMPLATE.with_name("bootstrap.yaml").read_text(), Loader=Loader)["Resources"]["CodeBucketTls"]["Properties"]["PolicyDocument"]["Statement"]
    matching = [statement for statement in statements if statement["Effect"] == "Allow"
                and statement.get("Condition", {}).get("ArnLike", {}).get("aws:SourceArn") == WORKER]
    assert len(matching) == 1
    statement = matching[0]
    assert statement["Principal"] == {"Service": "lambda.amazonaws.com"}
    assert statement["Action"] == ["s3:GetObject", "s3:GetObjectVersion"]
    assert statement["Resource"] == "arn:aws:s3:::code-bucket/web/*"
    assert statement["Condition"]["StringEquals"]["aws:SourceAccount"] == ACCOUNT
