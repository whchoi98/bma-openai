import fnmatch
import re
from pathlib import Path

import pytest
import yaml

ACCOUNT = "111122223333"
VALUES = {
    "AgentBackend": "bma", "AWS::NoValue": None,
    "AWS::Partition": "aws", "AWS::AccountId": ACCOUNT, "AWS::Region": "us-east-1",
    "AppRegion": "us-east-1", "TargetRegion": "ap-northeast-2",
    "RuntimeName": "bma_seoul_inventory", "RuntimeRepositoryName": "bma-seoul-runtime",
    "BmaModel": "openai.test-model", "ConverseModel": "global.openai.gpt-6-luna",
    "AWS::StackName": "bma-seoul-inventory", "WebEndpoint.DomainName": "example.lambda-web.us-east-1.on.aws",
    "WebDistribution.DomainName": "example.cloudfront.net",
    "MaxResources": "2", "MaxPages": "2", "MaxMetricHours": "1",
    "MaxDatapoints": "100", "MaxTurnSeconds": "300",
    "WebFunctionName": "bma-seoul-inventory-web", "CodeBucket.Arn": "arn:aws:s3:::code-bucket",
    "Runtime.AgentRuntimeArn": f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:runtime/demo-1234567890",
    "SessionRole.Arn": f"arn:aws:iam::{ACCOUNT}:role/BmaSession",
    "AppState.Arn": "arn:aws:s3:::app-state", "WebLogs.Arn": f"arn:aws:logs:us-east-1:{ACCOUNT}:log-group:web:*",
    "InvestigationWorker.Arn": f"arn:aws:lambda:us-east-1:{ACCOUNT}:function:bma-seoul-inventory-investigation-worker",
    "WorkerLogs.Arn": f"arn:aws:logs:us-east-1:{ACCOUNT}:log-group:worker:*",
    "InvestigationWorkerFunctionName": "bma-seoul-inventory-investigation-worker",
}


class Loader(yaml.SafeLoader):
    pass


def intrinsic(loader, tag, node):
    if tag == "If":
        _, yes, no = loader.construct_sequence(node, deep=True)
        return yes if VALUES["AgentBackend"] == "converse" else no
    if tag == "Ref":
        return VALUES.get(loader.construct_scalar(node), "fixture")
    if tag in {"Sub", "GetAtt"}:
        text = loader.construct_scalar(node)
        return VALUES.get(text, text) if tag == "GetAtt" else re.sub(r"\$\{([^}]+)\}", lambda m: VALUES[m[1]], text)
    return loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode) else loader.construct_scalar(node)


Loader.add_multi_constructor("!", intrinsic)
TEMPLATE = Path(__file__).resolve().parents[1] / "infra/template.yaml"


def statements(role):
    data = yaml.load(TEMPLATE.read_text(), Loader=Loader)
    return [statement for policy in data["Resources"][role]["Properties"]["Policies"]
            for statement in policy["PolicyDocument"]["Statement"] if statement is not None]


def allowed(role, action, resource="*", *, region="ap-northeast-2", **context):
    """Evaluate the Allow/implicit-Deny subset used by this template against concrete requests."""
    request = {"aws:RequestedRegion": region, **context}
    for statement in statements(role):
        actions, resources = statement["Action"], statement["Resource"]
        actions = actions if isinstance(actions, list) else [actions]
        resources = resources if isinstance(resources, list) else [resources]
        if not any(fnmatch.fnmatchcase(action, pattern) for pattern in actions):
            continue
        if not any(fnmatch.fnmatchcase(resource, pattern) for pattern in resources):
            continue
        matches = True
        for operator, conditions in statement.get("Condition", {}).items():
            for key, choices in conditions.items():
                choices = choices if isinstance(choices, list) else [choices]
                value = request.get(key)
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
        if not matches:
            continue
        if statement["Effect"] == "Allow":
            return True
    return False


@pytest.mark.parametrize("action,resource", [
    ("ec2:DescribeInstances", "*"), ("ec2:DescribeInstanceStatus", "*"),
    ("rds:DescribeDBInstances", f"arn:aws:rds:ap-northeast-2:{ACCOUNT}:db:orders"),
    ("ecs:ListClusters", "*"), ("ecs:ListServices", "*"),
    ("ecs:DescribeServices", f"arn:aws:ecs:ap-northeast-2:{ACCOUNT}:service/demo/api"),
    ("lambda:ListFunctions", "*"),
    ("lambda:GetFunctionConfiguration", f"arn:aws:lambda:ap-northeast-2:{ACCOUNT}:function:demo"),
    ("cloudwatch:GetMetricData", "*"), ("cloudwatch:DescribeAlarms", "*"),
])
def test_runtime_allows_implemented_queries_only_in_seoul(action, resource):
    assert allowed("RuntimeRole", action, resource)
    assert not allowed("RuntimeRole", action, resource, region="us-east-1")
    assert not allowed("WebRole", action, resource)
    assert not allowed("SessionRole", action, resource)


@pytest.mark.parametrize("action", [
    "ec2:StopInstances", "ec2:TerminateInstances", "ec2:RebootInstances", "rds:ModifyDBInstance",
    "rds:DeleteDBInstance", "ecs:UpdateService", "lambda:UpdateFunctionConfiguration",
    "lambda:ListWebFunctions", "cloudwatch:PutMetricAlarm", "logs:StartQuery", "ce:GetCostAndUsage",
    "sts:AssumeRole",
])
def test_runtime_does_not_allow_mutations_or_unimplemented_operations(action):
    assert not allowed("RuntimeRole", action)


def test_app_storage_is_not_constrained_to_target_region():
    assert allowed("WebRole", "s3:PutObject", "arn:aws:s3:::app-state/runs/run.json", region="us-east-1")
    assert not allowed("RuntimeRole", "s3:PutObject", "arn:aws:s3:::app-state/runs/run.json", region="us-east-1")


@pytest.mark.parametrize("action,resource", [
    ("ec2:DescribeVpcs", "*"), ("ec2:DescribeSubnets", "*"), ("ec2:DescribeSecurityGroups", "*"),
    ("ec2:DescribeRouteTables", "*"), ("ec2:DescribeInternetGateways", "*"),
    ("ec2:DescribeNatGateways", "*"), ("ec2:DescribeVpcEndpoints", "*"), ("ec2:DescribeVolumes", "*"),
    ("ecr:DescribeRepositories", f"arn:aws:ecr:ap-northeast-2:{ACCOUNT}:repository/example"),
    ("dynamodb:ListTables", "*"),
    ("dynamodb:DescribeTable", f"arn:aws:dynamodb:ap-northeast-2:{ACCOUNT}:table/example"),
    ("dynamodb:DescribeContinuousBackups", f"arn:aws:dynamodb:ap-northeast-2:{ACCOUNT}:table/example"),
    ("elasticache:DescribeCacheClusters", f"arn:aws:elasticache:ap-northeast-2:{ACCOUNT}:cluster:example"),
    ("es:ListDomainNames", "*"), ("es:DescribeDomain", f"arn:aws:es:ap-northeast-2:{ACCOUNT}:domain/example"),
    ("kafka:ListClustersV2", "*"), ("s3:ListAllMyBuckets", "*"),
])
def test_extended_queries_remain_read_only_and_seoul_scoped(action, resource):
    assert allowed("RuntimeRole", action, resource)
    assert not allowed("RuntimeRole", action, resource, region="us-east-1")
    assert not allowed("WebRole", action, resource)
    assert not allowed("SessionRole", action, resource)


@pytest.mark.parametrize("action", [
    "s3:GetEncryptionConfiguration", "s3:GetBucketPublicAccessBlock", "s3:GetBucketPolicyStatus", "s3:GetBucketVersioning",
])
def test_bucket_configuration_requires_owned_bucket(action):
    bucket = "arn:aws:s3:::example-owned-bucket"
    assert allowed("RuntimeRole", action, bucket, **{"s3:ResourceAccount": ACCOUNT})
    assert not allowed("RuntimeRole", action, bucket)
    assert not allowed("RuntimeRole", action, bucket, **{"s3:ResourceAccount": "999988887777"})
    assert not allowed("RuntimeRole", action, bucket, region="us-east-1", **{"s3:ResourceAccount": ACCOUNT})


@pytest.mark.parametrize("action", [
    "dynamodb:Query", "dynamodb:Scan", "dynamodb:PutItem", "s3:GetObject", "s3:PutObject",
    "ecr:StartImageScan", "ec2:DeleteVolume", "ec2:AuthorizeSecurityGroupIngress", "es:ESHttpGet",
    "kafka:GetBootstrapBrokers", "elasticache:ModifyCacheCluster",
])
def test_extended_runtime_does_not_gain_data_plane_or_mutation_permissions(action):
    assert not allowed("RuntimeRole", action)


def test_history_is_scoped_to_one_account_region_prefix_in_the_app_bucket():
    prefix = f"history/{ACCOUNT}/ap-northeast-2/"
    assert allowed("WebRole", "s3:ListBucket", "arn:aws:s3:::app-state", region="us-east-1", **{"s3:prefix": prefix})
    assert not allowed("WebRole", "s3:ListBucket", "arn:aws:s3:::app-state", **{"s3:prefix": "history/other/"})
    assert not allowed("WebRole", "s3:ListBucket", "arn:aws:s3:::app-state", **{"s3:prefix": "runs/"})
    assert allowed("WebRole", "s3:PutObject", "arn:aws:s3:::app-state/" + prefix + "index.json", region="us-east-1")
    assert not allowed("RuntimeRole", "s3:PutObject", "arn:aws:s3:::app-state/" + prefix + "index.json")


def test_session_role_only_connects_designated_runtime_and_model():
    arn = VALUES["Runtime.AgentRuntimeArn"]
    assert allowed("SessionRole", "bedrock-agentcore:InvokeAgentRuntime", arn, region="us-east-1")
    assert allowed("SessionRole", "bedrock-agentcore:StopRuntimeSession", arn + "/runtime-endpoint/DEFAULT")
    assert not allowed("SessionRole", "bedrock-agentcore:InvokeAgentRuntime", arn.replace("demo-", "other-"))
    assert allowed("SessionRole", "bedrock-mantle:CreateInference", **{"bedrock-mantle:Model": "openai.test-model"})
    assert not allowed("SessionRole", "bedrock-mantle:CreateInference", **{"bedrock-mantle:Model": "openai.other"})


def test_passrole_is_restricted_to_one_role_and_bma_service():
    role = VALUES["SessionRole.Arn"]
    assert allowed("WebRole", "iam:PassRole", role, **{"iam:PassedToService": "bedrock-mantle.amazonaws.com"})
    assert not allowed("WebRole", "iam:PassRole", role, **{"iam:PassedToService": "ec2.amazonaws.com"})
    assert not allowed("WebRole", "iam:PassRole", role + "Other", **{"iam:PassedToService": "bedrock-mantle.amazonaws.com"})


def test_converse_role_grants_only_designated_profile_and_web_role_assumption(monkeypatch):
    monkeypatch.setitem(VALUES, "AgentBackend", "converse")
    profile = f"arn:aws:bedrock:us-east-1:{ACCOUNT}:inference-profile/global.openai.gpt-6-luna"
    assert allowed("SessionRole", "bedrock:InvokeModelWithResponseStream", profile, region="us-east-1")
    assert not allowed("SessionRole", "bedrock:InvokeModelWithResponseStream", profile.replace("gpt-6-luna", "other"))
    assert not allowed("WebRole", "bedrock:InvokeModelWithResponseStream", profile)
    role = VALUES["SessionRole.Arn"]
    assert allowed("WebRole", "sts:AssumeRole", role, region="us-east-1")
    assert not allowed("WebRole", "sts:AssumeRole", role + "Other")
    trust = yaml.load(TEMPLATE.read_text(), Loader=Loader)["Resources"]["SessionRole"]["Properties"]["AssumeRolePolicyDocument"]["Statement"]
    web_trust = next(statement for statement in trust if "AWS" in statement["Principal"])
    assert web_trust["Principal"]["AWS"] == f"arn:aws:iam::{ACCOUNT}:root"
    assert web_trust["Condition"]["ArnLike"]["aws:PrincipalArn"] == f"arn:aws:iam::{ACCOUNT}:role/bma-seoul-inventory-WebRole-*"


def test_bma_session_role_does_not_grant_global_converse_inference():
    profile = f"arn:aws:bedrock:us-east-1:{ACCOUNT}:inference-profile/global.openai.gpt-6-luna"
    assert not allowed("SessionRole", "bedrock:InvokeModelWithResponseStream", profile, region="us-east-1")


def test_deployment_limits_are_identical_in_web_and_runtime():
    data = yaml.load(TEMPLATE.read_text(), Loader=Loader)["Resources"]
    runtime = data["Runtime"]["Properties"]["EnvironmentVariables"]
    web = data["WebRevision"]["Properties"]["ServiceConfig"]["EnvironmentVariables"]
    for name, value in {
        "MAX_RESOURCES": "2", "MAX_PAGES": "2", "MAX_METRIC_HOURS": "1", "MAX_DATAPOINTS": "100"
    }.items():
        assert runtime[name] == value
        assert web[name] == value
    assert web["MAX_TURN_SECONDS"] == "300"


def test_lambda_can_read_only_designated_web_revision_code():
    path = TEMPLATE.with_name("bootstrap.yaml")
    statements = yaml.load(path.read_text(), Loader=Loader)["Resources"]["CodeBucketTls"]["Properties"]["PolicyDocument"]["Statement"]

    def granted(action, resource, source):
        for statement in statements:
            if statement["Effect"] != "Allow":
                continue
            if statement["Principal"] != {"Service": "lambda.amazonaws.com"}:
                continue
            if action not in statement["Action"] or not fnmatch.fnmatchcase(resource, statement["Resource"]):
                continue
            if fnmatch.fnmatchcase(source, statement["Condition"]["ArnLike"]["aws:SourceArn"]):
                return True
        return False

    source = f"arn:aws:lambda:us-east-1:{ACCOUNT}:web-function/bma-seoul-inventory-web/revision/123"
    assert granted("s3:GetObject", "arn:aws:s3:::code-bucket/web/code.zip", source)
    assert granted("s3:GetObjectVersion", "arn:aws:s3:::code-bucket/web/code.zip", source)
    assert not granted("s3:GetObject", "arn:aws:s3:::code-bucket/private/secret", source)
    assert not granted("s3:GetObject", "arn:aws:s3:::code-bucket/web/code.zip", source.replace("inventory-web", "other-web"))
    assert not granted("s3:PutObject", "arn:aws:s3:::code-bucket/web/code.zip", source)
