#!/usr/bin/env python3
"""Stage CloudFront, bind exact OAC policies, then restrict both regional origins."""

import argparse
import concurrent.futures
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import boto3
import httpx
from botocore.config import Config
from botocore.exceptions import ClientError
from cfnlint.decode import decode_str

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "artifacts/cloudfront"
REGION = "us-east-1"
POLICY_SID = "AllowOnlyThisCloudFrontDistribution"
APPS = {
    "desk": {
        "manifest": "artifacts/aws-deployment.json",
        "template": "infra/template.yaml",
        "zip": "artifacts/web-function.zip",
        "stack": "bma-seoul-inventory",
        "endpoint": "demo",
        "worker": "InvestigationWorker",
        "model": "openai.gpt-6-luna",
        "context": "/api/context",
    },
    "studio": {
        "manifest": "artifacts/studio/deployment.json",
        "template": "studio/infra/template.yaml",
        "zip": "artifacts/studio/web-function.zip",
        "stack": "bma-office-studio",
        "endpoint": "studio",
        "worker": "StudioWorker",
        "model": "openai.gpt-6.1-sol",
        "context": "/api/config",
    },
}


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + "\n")


def endpoint_policy(account, function, endpoint, distribution):
    if not re.fullmatch(r"\d{12}", account):
        raise ValueError("InvalidAccount")
    if not re.fullmatch(r"E[A-Z0-9]+", distribution):
        raise ValueError("InvalidDistribution")
    if function not in {app["stack"] + "-web" for app in APPS.values()}:
        raise ValueError("UnexpectedFunction")
    expected_endpoint = "studio" if function == "bma-office-studio-web" else "demo"
    if endpoint != expected_endpoint:
        raise ValueError("UnexpectedEndpoint")
    return {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": POLICY_SID,
            "Effect": "Allow",
            "Principal": {"Service": "cloudfront.amazonaws.com"},
            "Action": "lambda:InvokeWebFunctionEndpoint",
            "Resource": f"arn:aws:lambda:{REGION}:{account}:web-function/{function}/endpoint/{endpoint}",
            "Condition": {
                "StringEquals": {
                    "aws:SourceArn": f"arn:aws:cloudfront::{account}:distribution/{distribution}",
                },
            },
        }],
    }


def review_changes(rows, worker, cutover=False, unchanged_web_role=False,
                   unchanged_distribution=False):
    allowed = {"WebEndpoint"} if cutover else {
        "WebRevision", "WebEndpoint", worker, "WebOriginAccessControl",
        "WebDistribution",
    }
    for row in rows:
        name = row["LogicalResourceId"]
        if name == "WebDistribution" and cutover and unchanged_distribution:
            details = row.get("Details", [])
            # AuthType changes do not change the origin hostname; CFN reevaluates GetAtt.
            if (row["Action"] == "Modify" and row.get("Replacement") == "False" and details
                    and all(item.get("Evaluation") == "Dynamic"
                            and item.get("ChangeSource") == "ResourceAttribute"
                            and item.get("CausingEntity") == "WebEndpoint.DomainName"
                            and item.get("Target") == {
                                "Attribute": "Properties", "Name": "DistributionConfig",
                                "RequiresRecreation": "Never",
                            } for item in details)):
                continue
        if name == "WebRole" and not cutover and unchanged_web_role:
            details = row.get("Details", [])
            # Updating worker code causes CFN to reevaluate its unchanged ARN reference.
            if (row["Action"] == "Modify" and row.get("Replacement") == "False" and details
                    and all(item.get("Evaluation") == "Dynamic"
                            and item.get("ChangeSource") == "ResourceAttribute"
                            and item.get("CausingEntity") == worker + ".Arn"
                            and item.get("Target") == {
                                "Attribute": "Properties", "Name": "Policies",
                                "RequiresRecreation": "Never",
                            } for item in details)):
                continue
        if name not in allowed or row["Action"] not in {"Add", "Modify"}:
            raise RuntimeError("UnexpectedResourceChange:" + name)
        if row.get("Replacement") in {"True", "Conditional"} and name != "WebRevision":
            raise RuntimeError("UnexpectedReplacement:" + name)


class Deployment:
    def __init__(self, app):
        self.app, self.spec = app, APPS[app]
        self.path = ROOT / self.spec["manifest"]
        self.data = json.loads(self.path.read_text())
        self.account = self.data["account_id"]
        if self.data["app_region"] != REGION or self.data["model"] != self.spec["model"]:
            raise RuntimeError("UnexpectedDeploymentScope")
        self.session = boto3.Session(region_name=REGION)
        self.config = Config(connect_timeout=5, read_timeout=30,
                             retries={"mode": "standard", "total_max_attempts": 3})
        if self.client("sts").get_caller_identity()["Account"] != self.account:
            raise RuntimeError("AccountMismatch")
        self.cf = self.client("cloudformation")
        self.web = self.client("lambda-web")
        self.cdn = self.client("cloudfront")
        self.function = self.spec["stack"] + "-web"
        self.function_arn = f"arn:aws:lambda:{REGION}:{self.account}:web-function/{self.function}"
        self.folder = STATE / app
        self.folder.mkdir(parents=True, exist_ok=True)
        stack = self.stack()
        if stack["StackName"] != self.spec["stack"]:
            raise RuntimeError("UnexpectedStack")
        backup = self.folder / "before-deployment.json"
        if not backup.exists():
            write_json(backup, self.data)
            original = self.cf.get_template(StackName=stack["StackId"])["TemplateBody"]
            (self.folder / "before-template.txt").write_text(
                original if isinstance(original, str) else json.dumps(original, indent=2))

    def client(self, name):
        return self.session.client(name, region_name=REGION, config=self.config)

    def stack(self):
        return self.cf.describe_stacks(StackName=self.data["main_stack_id"])["Stacks"][0]

    def endpoint(self):
        return self.web.get_web_function_endpoint(
            functionName=self.function, endpointName=self.spec["endpoint"])

    def policy(self):
        try:
            return self.web.get_resource_policy(resourceArn=self.function_arn)
        except ClientError as exc:
            if exc.response["Error"]["Code"] not in {"ResourceNotFoundException", "ResourceNotFound"}:
                raise
            return None

    def save(self, stack):
        self.data.update(
            outputs={row["OutputKey"]: row["OutputValue"] for row in stack["Outputs"]},
            stack_status=stack["StackStatus"], updated_at=now(),
        )
        endpoint = self.endpoint()
        self.data.update(web_revision=endpoint["revisionWeights"][0]["revisionId"],
                         web_auth_type=endpoint["authType"], web_status=endpoint["state"])
        write_json(self.path, self.data)

    def wait(self):
        for attempt in range(180):
            current = self.stack()
            status = current["StackStatus"]
            if status == "UPDATE_COMPLETE":
                return current
            if "FAILED" in status or "ROLLBACK" in status:
                events = self.cf.describe_stack_events(StackName=current["StackId"])["StackEvents"]
                write_json(self.folder / "failed-events.json", events)
                raise RuntimeError("StackUpdateFailed:" + status)
            if attempt % 4 == 0:
                print(json.dumps({"app": self.app, "stack_status": status}), flush=True)
            time.sleep(10)
        raise RuntimeError("StackWaitTimeout")

    def update(self, phase, overrides, cutover=False):
        stack = self.stack()
        if stack["StackStatus"] not in {"CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE"}:
            raise RuntimeError("StackNotReady:" + stack["StackStatus"])
        parameters = [
            {"ParameterKey": row["ParameterKey"], "UsePreviousValue": True}
            for row in stack["Parameters"] if row["ParameterKey"] not in overrides
        ] + [{"ParameterKey": key, "ParameterValue": value} for key, value in overrides.items()]
        template = (ROOT / self.spec["template"]).read_text()
        self.cf.validate_template(TemplateBody=template)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        change = self.cf.create_change_set(
            StackName=stack["StackId"], ChangeSetName=f"cloudfront-{phase}-{stamp}",
            ChangeSetType="UPDATE", TemplateBody=template, Parameters=parameters,
            Capabilities=["CAPABILITY_IAM"],
            Description="Scoped CloudFront OAC rollout; preserve BMA Runtime and data roles.",
        )["Id"]
        for _ in range(60):
            detail = self.cf.describe_change_set(ChangeSetName=change)
            if detail["Status"] == "CREATE_COMPLETE":
                break
            if detail["Status"] == "FAILED":
                if "didn't contain changes" in detail.get("StatusReason", ""):
                    return stack
                raise RuntimeError("ChangeSetFailed:" + detail.get("StatusReason", ""))
            time.sleep(3)
        else:
            raise RuntimeError("ChangeSetTimeout")
        rows = [item["ResourceChange"] for item in detail["Changes"]]
        write_json(self.folder / f"{phase}-changes.json", rows)
        previous = self.cf.get_template(StackName=stack["StackId"])["TemplateBody"]
        previous, errors = decode_str(previous) if isinstance(previous, str) else (previous, [])
        proposed, new_errors = decode_str(template)
        if errors or new_errors:
            raise RuntimeError("TemplateComparisonFailed")
        unchanged_web_role = previous["Resources"]["WebRole"] == proposed["Resources"]["WebRole"]
        unchanged_distribution = (previous["Resources"].get("WebDistribution")
                                  == proposed["Resources"].get("WebDistribution"))
        review_changes(rows, self.spec["worker"], cutover=cutover,
                       unchanged_web_role=unchanged_web_role,
                       unchanged_distribution=unchanged_distribution)
        print(json.dumps({"app": self.app, "phase": phase, "reviewed_resources": [
            row["LogicalResourceId"] for row in rows]}), flush=True)
        self.cf.execute_change_set(ChangeSetName=change, DisableRollback=False)
        # Ensure the request has entered UPDATE_IN_PROGRESS before accepting UPDATE_COMPLETE.
        time.sleep(3)
        result = self.wait()
        self.save(result)
        return result

    def prepare(self):
        existing = self.policy()
        if not (self.folder / "before-policy.json").exists():
            write_json(self.folder / "before-policy.json", existing)
        if existing:
            statements = json.loads(existing["policy"]).get("Statement", [])
            if any(statement.get("Sid") != POLICY_SID for statement in statements):
                raise RuntimeError("ExistingResourcePolicyRequiresReview")
        endpoint = self.endpoint()
        if endpoint["state"] != "Active":
            raise RuntimeError("EndpointNotActive")
        path = ROOT / self.spec["zip"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        key = f"web/{digest}.zip"
        response = self.client("s3").put_object(
            Bucket=self.data["code_bucket"], Key=key, Body=path.read_bytes(),
            ExpectedBucketOwner=self.account, ServerSideEncryption="AES256")
        pending = {"CodeKey": key, "CodeVersionId": response["VersionId"],
                   "WebEndpointAuthType": endpoint["authType"]}
        write_json(self.folder / "pending-artifact.json", pending)
        self.update("prepare", pending)
        self.data.update(code_key=key, code_version_id=response["VersionId"], web_zip_sha256=digest)
        write_json(self.path, self.data)
        print(json.dumps({"app": self.app, "phase": "prepared",
                          "url": self.data["outputs"]["WebUrl"]}), flush=True)

    def cutover(self):
        outputs = self.data["outputs"]
        distribution = outputs["DistributionId"]
        current = self.cdn.get_distribution(Id=distribution)["Distribution"]
        if current["Status"] != "Deployed":
            raise RuntimeError("DistributionNotDeployed")
        expected_origin = urlparse(outputs["OriginWebUrl"]).hostname
        origins = current["DistributionConfig"]["Origins"]["Items"]
        if len(origins) != 1 or origins[0]["DomainName"] != expected_origin:
            raise RuntimeError("UnexpectedDistributionOrigin")
        desired = endpoint_policy(self.account, self.function, self.spec["endpoint"], distribution)
        existing = self.policy()
        if existing:
            if any(row.get("Sid") != POLICY_SID for row in json.loads(existing["policy"]).get("Statement", [])):
                raise RuntimeError("ExistingResourcePolicyRequiresReview")
        if not existing or json.loads(existing["policy"]) != desired:
            args = {"resourceArn": self.function_arn, "policy": json.dumps(desired)}
            if existing:
                args["revisionId"] = existing["revisionId"]
            self.web.put_resource_policy(**args)
        actual = self.policy()
        if not actual or json.loads(actual["policy"]) != desired:
            raise RuntimeError("ResourcePolicyNotApplied")
        write_json(self.folder / "resource-policy.json", desired)
        token_path = ROOT / self.data["secret_file"]
        token = json.loads(token_path.read_text())["app_access_token"]
        # Prove the new viewer URL preserves app authentication before retiring direct access.
        with httpx.Client(timeout=30) as client:
            for _ in range(20):
                edge = client.get(outputs["WebUrl"] + self.spec["context"],
                                  headers={"Authorization": "Bearer " + token})
                if edge.status_code == 200 and edge.headers.get("x-amz-cf-id"):
                    break
                time.sleep(5)
            else:
                raise RuntimeError("EdgePreflightFailedOriginAuthUnchanged")
        self.update("cutover", {"WebEndpointAuthType": "IamAuth"}, cutover=True)
        # A failed post-cutover check is fail-closed. Never silently reopen an OAC origin.
        with httpx.Client(timeout=30) as client:
            for attempt in range(30):
                edge = client.get(outputs["WebUrl"] + self.spec["context"],
                                  headers={"Authorization": "Bearer " + token})
                direct = client.get(outputs["OriginWebUrl"] + "/")
                if edge.status_code == 200 and direct.status_code == 403:
                    break
                if attempt % 5 == 0:
                    print(json.dumps({"app": self.app, "phase": "propagating",
                                      "edge_status": edge.status_code, "origin_status": direct.status_code}),
                          flush=True)
                time.sleep(5)
            else:
                raise RuntimeError("CutoverHttpVerificationFailed")
        runtime = self.client("bedrock-agentcore-control").get_agent_runtime(
            agentRuntimeId=outputs["RuntimeArn"].rsplit("/", 1)[1])
        if str(runtime["agentRuntimeVersion"]) != str(self.data["runtime_version"]):
            raise RuntimeError("UnexpectedRuntimeChange")
        endpoint = self.endpoint()
        if endpoint["authType"] != "IamAuth":
            raise RuntimeError("EndpointNotPrivate")
        self.data.update(cloudfront_status="deployed", cloudfront_deployed_at=now())
        write_json(self.path, self.data)
        print(json.dumps({"app": self.app, "phase": "cutover_complete",
                          "url": outputs["WebUrl"], "origin_status": direct.status_code}), flush=True)

    def mapping(self):
        outputs = self.data["outputs"]
        return {
            "distribution_id": outputs["DistributionId"],
            "domain": urlparse(outputs["WebUrl"]).hostname,
            "origin_url": outputs["OriginWebUrl"],
            "deployment_manifest": self.spec["manifest"],
            "oac_id": outputs["OriginAccessControlId"],
            "endpoint_auth": self.endpoint()["authType"],
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["prepare", "cutover", "all", "inspect"])
    parser.add_argument("--app", choices=["desk", "studio", "both"], default="both")
    args = parser.parse_args()
    names = list(APPS) if args.app == "both" else [args.app]

    def run(name):
        deployment = Deployment(name)
        if args.phase in {"prepare", "all"}:
            deployment.prepare()
        if args.phase in {"cutover", "all"}:
            deployment.cutover()
        return name, deployment.mapping()

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(run, name) for name in names]
        for task in concurrent.futures.as_completed(pending):
            name, mapping = task.result()
            results[name] = mapping
    path = STATE / "deployment.json"
    previous = json.loads(path.read_text()) if path.exists() else {"app_region": REGION, "apps": {}}
    previous["apps"].update(results)
    previous["updated_at"] = now()
    write_json(path, previous)
    print(json.dumps(previous, indent=2), flush=True)


if __name__ == "__main__":
    main()
