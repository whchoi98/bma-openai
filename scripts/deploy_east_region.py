#!/usr/bin/env python3
"""Deploy the approved Virginia BMA migration in explicit, restartable phases."""
import argparse
import base64
import hashlib
import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.config import Config

from deployment_parameters import parameters

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "artifacts/migration-east"
REGION = "us-east-1"
MODEL = "openai.gpt-6-luna"
CONFIG = Config(connect_timeout=4, read_timeout=30,
                retries={"mode": "standard", "total_max_attempts": 3})


class Deployment:
    def __init__(self):
        self.discovery = json.loads((STATE / "discovery.json").read_text())
        self.account = self.discovery["account_id"]
        self.session = boto3.Session()
        if self.client("sts").get_caller_identity()["Account"] != self.account:
            raise RuntimeError("AccountMismatch")
        if MODEL not in self.discovery["model_ids"]:
            raise RuntimeError("ModelNotDiscovered")
        if json.loads((STATE / "cleanup.json").read_text()).get("deletion_status") != "completed":
            raise RuntimeError("OldDeploymentNotRetired")
        if json.loads((STATE / "deletion-verification.json").read_text()).get("status") != "passed":
            raise RuntimeError("OldDeploymentDeletionNotVerified")
        self.path = STATE / "new-deployment.json"
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {
            "account_id": self.account, "app_region": REGION, "target_region": "ap-northeast-2",
            "agent_backend": "bma", "model": MODEL, "model_processing_scope": "app_region",
            "display_model": "Luna", "display_name": "AI-Powered AWS Operations Desk",
            "secret_file": "artifacts/deployment-secrets.json",
            "source_repository": "/home/ec2-user/my-project/awsops",
            "e2e_directory": "artifacts/migration-east/e2e",
            "extended_e2e_directory": "artifacts/migration-east/e2e-extended",
            "ui_e2e_directory": "artifacts/migration-east/e2e-ui",
            "limits": {"max_resources": 2, "max_pages": 2, "max_metric_hours": 1,
                       "max_datapoints": 100, "max_turn_seconds": 300},
            "started_at": self.now(),
        }
        if self.data["account_id"] != self.account or self.data["app_region"] != REGION:
            raise RuntimeError("DeploymentRecordScopeMismatch")
        self.data.setdefault("ui_e2e_directory", "artifacts/migration-east/e2e-ui")

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    def client(self, name):
        return self.session.client(name, region_name=REGION, config=CONFIG)

    def save(self):
        self.data["updated_at"] = self.now()
        self.path.write_text(json.dumps(self.data, indent=2) + "\n")

    def wait(self, identifier):
        cf = self.client("cloudformation")
        for attempt in range(150):
            stack = cf.describe_stacks(StackName=identifier)["Stacks"][0]
            status = stack["StackStatus"]
            if status in {"CREATE_COMPLETE", "UPDATE_COMPLETE"}:
                return stack
            if "FAILED" in status or "ROLLBACK" in status:
                events = cf.describe_stack_events(StackName=identifier)["StackEvents"]
                (STATE / "failed-stack-events.json").write_text(json.dumps(events, indent=2, default=str) + "\n")
                raise RuntimeError(f"Deployment failed: {status}; see failed-stack-events.json")
            if attempt % 5 == 0:
                print(json.dumps({"stack": stack["StackName"], "status": status}), flush=True)
            time.sleep(10)
        raise RuntimeError("StackWaitTimeout")

    def create(self, name, template, key, inputs=None):
        if key not in self.data:
            result = self.client("cloudformation").create_stack(
                StackName=name, TemplateBody=(ROOT / template).read_text(),
                Parameters=inputs or [], Capabilities=["CAPABILITY_IAM"],
                Tags=[{"Key": "Project", "Value": "bma-seoul-inventory"},
                      {"Key": "DeploymentRegion", "Value": REGION}],
            )
            self.data[key] = result["StackId"]
            self.save()
        return self.wait(self.data[key])

    def bootstrap(self):
        stack = self.create("bma-seoul-build", "infra/bootstrap.yaml", "bootstrap_stack_id")
        self.data["bootstrap_outputs"] = {x["OutputKey"]: x["OutputValue"] for x in stack["Outputs"]}
        self.save()
        print("Virginia bootstrap stack ready.", flush=True)

    def artifacts(self):
        ecr = self.client("ecr")
        repository = self.data["bootstrap_outputs"]["RuntimeRepositoryUri"]
        if repository != f"{self.account}.dkr.ecr.{REGION}.amazonaws.com/bma-seoul-runtime":
            raise RuntimeError("UnexpectedRepository")
        image = subprocess.check_output(
            ["docker", "image", "inspect", "bma-seoul-runtime:0.1.0", "--format", "{{.Id}}"], text=True
        ).strip()
        tag = "east-" + image.split(":")[1][:16]
        destination = repository + ":" + tag
        subprocess.run(["docker", "tag", "bma-seoul-runtime:0.1.0", destination], check=True)
        token = ecr.get_authorization_token(registryIds=[self.account])["authorizationData"][0]
        username, password = base64.b64decode(token["authorizationToken"]).decode().split(":", 1)
        with tempfile.TemporaryDirectory(prefix="bma-ecr-auth-") as auth:
            subprocess.run(
                ["docker", "--config", auth, "login", "--username", username, "--password-stdin",
                 repository.split("/")[0]],
                input=password.encode(), check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            subprocess.run(["docker", "--config", auth, "push", destination], check=True)
        detail = ecr.describe_images(registryId=self.account, repositoryName="bma-seoul-runtime",
                                     imageIds=[{"imageTag": tag}])["imageDetails"][0]
        self.data["runtime_image_tag"] = tag
        self.data["runtime_image_uri"] = repository + "@" + detail["imageDigest"]
        self.data["local_image_id"] = image
        bucket = self.data["bootstrap_outputs"]["CodeBucket"]
        path = ROOT / "artifacts/web-function.zip"
        with path.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        key = f"web/{checksum}.zip"
        with path.open("rb") as stream:
            result = self.client("s3").put_object(
                Bucket=bucket, Key=key, Body=stream, ExpectedBucketOwner=self.account,
                ServerSideEncryption="AES256",
            )
        self.data.update(code_bucket=bucket, code_key=key, code_version_id=result["VersionId"],
                         web_zip_sha256=checksum, artifacts_uploaded_at=self.now())
        self.save()
        print("Virginia Runtime image and Web Function ZIP uploaded.", flush=True)

    def main(self):
        context = {
            "expected_account_id": self.account, "app_region": REGION, "target_region": "ap-northeast-2",
            "available_model_ids": self.discovery["model_ids"], "verified_at": self.now(),
            "verification_api": "STS.GetCallerIdentity; regional Mantle model catalog",
        }
        (ROOT / "artifacts/deployment-context.json").write_text(json.dumps(context, indent=2) + "\n")
        secret = json.loads((ROOT / self.data["secret_file"]).read_text())["app_access_token"]
        env = {
            "APP_REGION": REGION, "TARGET_REGION": "ap-northeast-2", "EXPECTED_ACCOUNT_ID": self.account,
            "BMA_ECR_URI": self.data["bootstrap_outputs"]["RuntimeRepositoryUri"],
            "BMA_IMAGE_DIGEST": self.data["runtime_image_uri"].split("@")[1],
            "BMA_MODEL": MODEL, "AGENT_BACKEND": "bma", "APP_ACCESS_TOKEN": secret,
            "BMA_CODE_BUCKET": self.data["code_bucket"], "BMA_CODE_KEY": self.data["code_key"],
            "BMA_CODE_VERSION": self.data["code_version_id"],
            "MAX_RESOURCES": "2", "MAX_PAGES": "2", "MAX_METRIC_HOURS": "1",
            "MAX_DATAPOINTS": "100", "MAX_TURN_SECONDS": "300",
        }
        inputs = parameters(env, context, self.account)
        fd = os.open(ROOT / "artifacts/deploy-parameters.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(inputs, stream, indent=2)
        stack = self.create("bma-seoul-inventory", "infra/template.yaml", "main_stack_id", inputs)
        self.data["outputs"] = {x["OutputKey"]: x["OutputValue"] for x in stack["Outputs"]}
        self.data["stack_status"] = stack["StackStatus"]
        self.save()
        self.inspect()

    def inspect(self):
        runtime_id = self.data["outputs"]["RuntimeArn"].rsplit("/", 1)[1]
        runtime = self.client("bedrock-agentcore-control").get_agent_runtime(agentRuntimeId=runtime_id)
        endpoint = self.client("lambda-web").get_web_function_endpoint(
            functionName="bma-seoul-inventory-web", endpointName="demo"
        )
        self.data["runtime_version"] = runtime["agentRuntimeVersion"]
        self.data["web_revision"] = endpoint["revisionWeights"][0]["revisionId"]
        self.data["runtime_status"] = runtime["status"]
        self.data["web_endpoint_status"] = endpoint["state"]
        contract = json.loads((ROOT / "web/contract.json").read_text())
        self.data["mcp_tools"] = contract["tools"]
        self.data["skills"] = [row["name"] for row in contract["skills"]]
        self.data["supported_services"] = contract["supported_services"]
        self.save()
        (ROOT / "artifacts/aws-deployment.json").write_text(json.dumps(self.data, indent=2) + "\n")
        print(json.dumps({
            "region": REGION, "model": MODEL, "backend": "bma",
            "runtime_status": self.data["runtime_status"],
            "endpoint_status": self.data["web_endpoint_status"],
            "web_revision": self.data["web_revision"],
        }, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["bootstrap", "artifacts", "main", "inspect"])
    args = parser.parse_args()
    getattr(Deployment(), args.phase)()
