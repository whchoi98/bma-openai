"""Evaluate concrete Studio IAM requests and deployment boundaries locally."""
import fnmatch
import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ACCOUNT = "111122223333"
REGION = "us-east-1"
UUID = "11111111-2222-4333-8444-555555555555"
BUCKET = "arn:aws:s3:::studio-data"
RUNTIME = f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:runtime/bma_office_documents-abc"
WORKER = f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:bma-office-studio-worker"
SESSION = f"arn:aws:iam::{ACCOUNT}:role/studio-session"
VALUES = {
    "AWS::Partition": "aws", "AWS::Region": REGION, "AWS::AccountId": ACCOUNT,
    "AWS::StackName": "bma-office-studio", "AppRegion": REGION,
    "RuntimeName": "bma_office_documents", "RuntimeRepositoryName": "bma-office-runtime",
    "WebFunctionName": "bma-office-studio-web", "WorkerFunctionName": "bma-office-studio-worker",
    "BmaModel": "openai.gpt-6-luna", "StudioData": "studio-data", "StudioData.Arn": BUCKET,
    "CodeBucket.Arn": "arn:aws:s3:::studio-code", "CodeBucket": "studio-code",
    "CodeKey": "web/studio.zip", "CodeVersionId": "version-123",
    "Runtime.AgentRuntimeArn": RUNTIME, "SessionRole.Arn": SESSION, "StudioWorker.Arn": WORKER,
    "WorkerRole.Arn": f"arn:aws:iam::{ACCOUNT}:role/studio-worker",
    "WebRole.Arn": f"arn:aws:iam::{ACCOUNT}:role/studio-web",
    "RuntimeRole.Arn": f"arn:aws:iam::{ACCOUNT}:role/studio-runtime",
    "WorkerLogs.Arn": f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:studio-worker:*",
    "WebLogs.Arn": f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:studio-web:*",
}


class Loader(yaml.SafeLoader):
    pass


def intrinsic(loader, tag, node):
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    text = loader.construct_scalar(node)
    if tag in {"Ref", "GetAtt"}:
        return VALUES.get(text, text)
    if tag == "Sub":
        return re.sub(r"\$\{([^}]+)\}", lambda m: VALUES.get(m[1], m[1]), text)
    return text


Loader.add_multi_constructor("!", intrinsic)


def as_list(value):
    return value if isinstance(value, list) else [value]


def matches_condition(conditions, context):
    for operator, entries in conditions.items():
        for key, expected in entries.items():
            actual, expected = context.get(key), as_list(expected)
            if operator in {"StringEquals", "ArnEquals"}:
                passed = actual in expected
            elif operator in {"StringLike", "ArnLike"}:
                passed = isinstance(actual, str) and any(fnmatch.fnmatchcase(actual, choice) for choice in expected)
            elif operator == "NumericLessThanEquals":
                try:
                    passed = actual is not None and any(float(actual) <= float(choice) for choice in expected)
                except (TypeError, ValueError):
                    passed = False
            elif operator == "Bool":
                passed = str(actual).lower() in [str(choice).lower() for choice in expected]
            else:
                passed = False
            if not passed:
                return False
    return True


def policy_allows(statements, action, resource, context=None):
    permitted = False
    for statement in statements:
        if (not any(fnmatch.fnmatchcase(action, pattern) for pattern in as_list(statement.get("Action", [])))
                or not any(fnmatch.fnmatchcase(resource, pattern) for pattern in as_list(statement.get("Resource", "*")))
                or not matches_condition(statement.get("Condition", {}), context or {})):
            continue
        if statement["Effect"] == "Deny":
            return False
        permitted |= statement["Effect"] == "Allow"
    return permitted


class InfraTests(unittest.TestCase):
    def setUp(self):
        self.template_path = ROOT / "studio/infra/template.yaml"
        self.assertTrue(self.template_path.is_file(), "Studio deployment template must exist")
        self.template = yaml.load(self.template_path.read_text(), Loader=Loader)
        self.resources = self.template["Resources"]

    def statements(self, role):
        return [statement for policy in self.resources[role]["Properties"]["Policies"]
                for statement in policy["PolicyDocument"]["Statement"]]

    def allowed(self, role, action, resource, **context):
        return policy_allows(self.statements(role), action, resource, context)

    def test_web_only_dispatches_designated_worker_and_has_no_bma_permissions(self):
        self.assertTrue(self.allowed("WebRole", "lambda:InvokeFunction", WORKER))
        for arn in (WORKER + "-other", WORKER.replace(ACCOUNT, "999988887777"), WORKER.replace(REGION, "us-west-2")):
            self.assertFalse(self.allowed("WebRole", "lambda:InvokeFunction", arn))
        for role in ("WebRole", "WorkerRole", "RuntimeRole"):
            for action in ("bedrock-mantle:CreateInference", "bedrock:InvokeModel", "bedrock-agentcore:InvokeAgentRuntime", "sts:AssumeRole"):
                for resource in ("*", RUNTIME, SESSION):
                    self.assertFalse(self.allowed(role, action, resource))
        self.assertFalse(self.allowed("WebRole", "bedrock-mantle:CreateAgentSession", f"arn:aws:bedrock-mantle:{REGION}:{ACCOUNT}:project/default"))

    def test_worker_six_session_actions_are_account_and_region_scoped(self):
        arn = f"arn:aws:bedrock-mantle:{REGION}:{ACCOUNT}:project/default"
        for name in ("CreateAgentSession", "GetAgentSession", "ListAgentSessions", "CreateAgentSessionEvent", "ListAgentSessionEvents", "ListAgentSessionItems"):
            action = "bedrock-mantle:" + name
            self.assertTrue(self.allowed("WorkerRole", action, arn))
            self.assertFalse(self.allowed("WorkerRole", action, arn.replace(ACCOUNT, "999988887777")))
            self.assertFalse(self.allowed("WorkerRole", action, arn.replace(REGION, "us-west-2")))
        self.assertTrue(self.allowed("WorkerRole", "iam:PassRole", SESSION, **{"iam:PassedToService": "bedrock-mantle.amazonaws.com"}))
        self.assertFalse(self.allowed("WorkerRole", "iam:PassRole", SESSION + "-other", **{"iam:PassedToService": "bedrock-mantle.amazonaws.com"}))
        self.assertFalse(self.allowed("WorkerRole", "iam:PassRole", SESSION, **{"iam:PassedToService": "lambda.amazonaws.com"}))

    def test_session_model_runtime_and_trust_are_restricted(self):
        self.assertTrue(self.allowed("SessionRole", "bedrock-mantle:CreateInference", "*", **{"bedrock-mantle:Model": "openai.gpt-6-luna"}))
        self.assertFalse(self.allowed("SessionRole", "bedrock-mantle:CreateInference", "*", **{"bedrock-mantle:Model": "openai.other"}))
        for action in ("bedrock-agentcore:InvokeAgentRuntime", "bedrock-agentcore:StopRuntimeSession"):
            self.assertTrue(self.allowed("SessionRole", action, RUNTIME))
            self.assertTrue(self.allowed("SessionRole", action, RUNTIME + "/runtime-endpoint/DEFAULT"))
            self.assertFalse(self.allowed("SessionRole", action, RUNTIME + "-other"))
        trust = self.resources["SessionRole"]["Properties"]["AssumeRolePolicyDocument"]["Statement"]
        self.assertEqual(len(trust), 1)
        self.assertEqual(trust[0]["Principal"], {"Service": "bedrock-mantle.amazonaws.com"})
        conditions = trust[0]["Condition"]
        context = {"aws:SourceAccount": ACCOUNT, "aws:SourceArn": f"arn:aws:bedrock-mantle:{REGION}:{ACCOUNT}:project/default"}
        self.assertTrue(matches_condition(conditions, context))
        self.assertFalse(matches_condition(conditions, {**context, "aws:SourceAccount": "999988887777"}))
        self.assertFalse(matches_condition(conditions, {**context, "aws:SourceArn": context["aws:SourceArn"].replace(REGION, "us-west-2")}))

    def test_role_s3_read_write_separation(self):
        keys = {
            "upload": f"uploads/{UUID}/data", "meta": f"uploads/{UUID}/meta.json",
            "input": f"jobs/{UUID}/input.json", "state": f"jobs/{UUID}/state.json",
            "artifacts": f"jobs/{UUID}/artifacts.json", "output": f"jobs/{UUID}/outputs/documents.pptx",
            "index": f"index/8227798399999-{UUID}.json",
        }
        permissions = {
            "WebRole": ({"meta", "input", "state", "output", "index"}, {"upload", "meta", "input", "state", "index"}),
            "WorkerRole": ({"input", "state", "artifacts", "index"}, {"state", "index"}),
            "RuntimeRole": ({"upload", "input", "artifacts", "output"}, {"artifacts", "output"}),
            "SessionRole": (set(), set()),
        }
        for role, (reads, writes) in permissions.items():
            for label, key in keys.items():
                resource = BUCKET + "/" + key
                self.assertEqual(self.allowed(role, "s3:GetObject", resource), label in reads, (role, "get", key))
                self.assertEqual(self.allowed(role, "s3:PutObject", resource), label in writes, (role, "put", key))
                self.assertFalse(self.allowed(role, "s3:DeleteObject", resource))
                self.assertFalse(self.allowed(role, "s3:GetObject", resource.replace("studio-data", "desk-data")))

    def test_exact_key_probes_and_index_listing_are_bounded(self):
        expected = {
            "WebRole": [f"uploads/{UUID}/meta.json", f"jobs/{UUID}/input.json", f"jobs/{UUID}/state.json", f"index/8227798399999-{UUID}.json", f"jobs/{UUID}/outputs/chart_1.png", f"jobs/{UUID}/outputs/preview.html"],
            "WorkerRole": [f"jobs/{UUID}/input.json", f"jobs/{UUID}/state.json", f"jobs/{UUID}/artifacts.json", f"index/8227798399999-{UUID}.json"],
            "RuntimeRole": [f"uploads/{UUID}/data", f"jobs/{UUID}/input.json", f"jobs/{UUID}/artifacts.json", f"jobs/{UUID}/outputs/chart_1.svg", f"jobs/{UUID}/outputs/documents.docx"],
        }
        for role, keys in expected.items():
            for key in keys:
                self.assertTrue(self.allowed(role, "s3:ListBucket", BUCKET, **{"s3:prefix": key, "s3:max-keys": 1}), (role, key))
                for size in (2, 20, 1000, None):
                    self.assertFalse(self.allowed(role, "s3:ListBucket", BUCKET, **{"s3:prefix": key, "s3:max-keys": size}))
                self.assertFalse(self.allowed(role, "s3:ListBucket", BUCKET, **{"s3:prefix": key + "/extra", "s3:max-keys": 1}))
            for key in ("", "jobs/", "uploads/", f"jobs/{UUID}/", f"jobs/{UUID}/outputs/"):
                self.assertFalse(self.allowed(role, "s3:ListBucket", BUCKET, **{"s3:prefix": key, "s3:max-keys": 1}))
        self.assertTrue(self.allowed("WebRole", "s3:ListBucket", BUCKET, **{"s3:prefix": "index/", "s3:max-keys": 20}))
        for role in ("WebRole", "WorkerRole", "RuntimeRole", "SessionRole"):
            self.assertFalse(self.allowed(role, "s3:ListBucket", BUCKET, **{"s3:prefix": "index/", "s3:max-keys": 21}))
        self.assertFalse(self.allowed("RuntimeRole", "s3:ListBucket", BUCKET, **{"s3:prefix": f"jobs/{UUID}/state.json", "s3:max-keys": 1}))
        self.assertFalse(self.allowed("WebRole", "s3:ListBucket", BUCKET, **{"s3:prefix": f"jobs/{UUID}/artifacts.json", "s3:max-keys": 1}))

    def test_runtime_only_has_environment_connection_and_own_infrastructure(self):
        project = f"arn:aws:bedrock-mantle:{REGION}:{ACCOUNT}:project/default"
        for action in ("bedrock-mantle:RegisterEnvironment", "bedrock-mantle:ConnectEnvironment"):
            self.assertTrue(self.allowed("RuntimeRole", action, project))
            self.assertFalse(self.allowed("RuntimeRole", action, project.replace(REGION, "us-west-2")))
        repository = f"arn:aws:ecr:{REGION}:{ACCOUNT}:repository/bma-office-runtime"
        self.assertTrue(self.allowed("RuntimeRole", "ecr:BatchGetImage", repository))
        self.assertFalse(self.allowed("RuntimeRole", "ecr:BatchGetImage", repository.replace("office", "seoul")))
        own_log = f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/bedrock-agentcore/runtimes/bma_office_documents-abc:log-stream:runtime"
        self.assertTrue(self.allowed("RuntimeRole", "logs:PutLogEvents", own_log))
        self.assertFalse(self.allowed("RuntimeRole", "logs:PutLogEvents", own_log.replace("bma_office_documents", "bma_seoul_inventory")))
        for role in ("WebRole", "WorkerRole", "RuntimeRole", "SessionRole"):
            for action in ("ec2:DescribeInstances", "s3:ListAllMyBuckets", "lambda:ListFunctions", "cloudwatch:GetMetricData", "iam:ListRoles"):
                self.assertFalse(self.allowed(role, action, "*"))

    def test_worker_deployment_is_bounded_and_secret_stays_in_web(self):
        worker = self.resources["StudioWorker"]["Properties"]
        self.assertEqual(worker["FunctionName"], "bma-office-studio-worker")
        self.assertEqual(worker["Runtime"], "nodejs24.x")
        self.assertEqual(worker["Handler"], "studio/web/worker.handler")
        self.assertEqual(worker["Architectures"], ["arm64"])
        self.assertEqual(worker["MemorySize"], 512)
        self.assertEqual(worker["Timeout"], 360)
        self.assertEqual(worker["ReservedConcurrentExecutions"], 2)
        self.assertEqual(worker["Code"], {"S3Bucket": "studio-code", "S3Key": "web/studio.zip", "S3ObjectVersion": "version-123"})
        env = worker["Environment"]["Variables"]
        web = self.resources["WebRevision"]["Properties"]
        self.assertEqual(web["BuildConfig"]["CodeConfig"]["S3Object"], {"Bucket": "studio-code", "Key": "web/studio.zip", "VersionId": "version-123"})
        webenv = web["ServiceConfig"]["EnvironmentVariables"]
        for key in ("APP_REGION", "EXPECTED_ACCOUNT_ID", "BMA_MODEL", "BMA_RUNTIME_ARN", "BMA_SESSION_ROLE_ARN", "STUDIO_BUCKET"):
            self.assertEqual(env[key], webenv[key])
        self.assertEqual(webenv["STUDIO_WORKER_ARN"], WORKER)
        self.assertNotIn("APP_ACCESS_TOKEN", env)
        self.assertNotIn("STUDIO_WORKER_ARN", env)
        self.assertTrue(self.template["Parameters"]["AppAccessToken"]["NoEcho"])
        retry = self.resources["StudioWorkerAsync"]["Properties"]
        self.assertEqual(retry["MaximumRetryAttempts"], 1)
        self.assertEqual(retry["MaximumEventAgeInSeconds"], 600)

    def test_storage_retention_and_runtime_lifecycle_are_separate(self):
        props = self.resources["StudioData"]["Properties"]
        self.assertTrue(all(props["PublicAccessBlockConfiguration"].values()))
        self.assertEqual(props["VersioningConfiguration"]["Status"], "Enabled")
        self.assertEqual(props["BucketEncryption"]["ServerSideEncryptionConfiguration"][0]["ServerSideEncryptionByDefault"]["SSEAlgorithm"], "AES256")
        rules = props["LifecycleConfiguration"]["Rules"]
        self.assertEqual({r["Prefix"] for r in rules}, {"uploads/", "jobs/", "index/"})
        for rule in rules:
            self.assertEqual(rule["ExpirationInDays"], 7)
            self.assertEqual(rule["NoncurrentVersionExpiration"]["NoncurrentDays"], 1)
        runtime = self.resources["Runtime"]["Properties"]
        self.assertEqual(runtime["PlatformVersion"], "V2")
        self.assertEqual(runtime["ProtocolConfiguration"], "HTTP")
        self.assertEqual(runtime["EnvironmentVariables"]["STUDIO_BUCKET"], "studio-data")
        self.assertEqual(runtime["EnvironmentVariables"]["BMA_CODEX_BINARY"], "/opt/bma/bin/codex")
        self.assertNotIn("TARGET_REGION", runtime["EnvironmentVariables"])

    def test_bootstrap_code_is_readable_only_by_designated_functions(self):
        path = ROOT / "studio/infra/bootstrap.yaml"
        self.assertTrue(path.is_file())
        template = yaml.load(path.read_text(), Loader=Loader)
        statements = template["Resources"]["CodeBucketPolicy"]["Properties"]["PolicyDocument"]["Statement"]
        for arn in (WORKER, f"arn:aws:lambda:{REGION}:{ACCOUNT}:web-function/bma-office-studio-web/revision/abc"):
            context = {"aws:SourceArn": arn, "aws:SourceAccount": ACCOUNT, "aws:SecureTransport": True}
            self.assertTrue(policy_allows(statements, "s3:GetObject", "arn:aws:s3:::studio-code/web/studio.zip", context))
            self.assertFalse(policy_allows(statements, "s3:GetObject", "arn:aws:s3:::studio-code/other/studio.zip", context))
            self.assertFalse(policy_allows(statements, "s3:GetObject", "arn:aws:s3:::studio-code/web/studio.zip", {**context, "aws:SourceArn": arn.replace("office", "seoul")}))
            self.assertFalse(policy_allows(statements, "s3:GetObject", "arn:aws:s3:::studio-code/web/studio.zip", {**context, "aws:SourceAccount": "999988887777"}))
            self.assertFalse(policy_allows(statements, "s3:GetObject", "arn:aws:s3:::studio-code/web/studio.zip", {**context, "aws:SecureTransport": False}))


if __name__ == "__main__":
    unittest.main()
