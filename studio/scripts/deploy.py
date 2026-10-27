#!/usr/bin/env python3
"""Deploy the separate AI Document Studio, never the AWS Operations Desk stack."""
import argparse
import base64
import hashlib
import json
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "artifacts/studio"
REGION = "us-east-1"


class Deployment:
    def __init__(self):
        existing = json.loads((ROOT / "artifacts/aws-deployment.json").read_text())
        self.account = existing["account_id"]
        self.session = boto3.Session()
        self.config = Config(connect_timeout=4, read_timeout=30,
                             retries={"mode": "standard", "total_max_attempts": 3})
        if self.client("sts").get_caller_identity()["Account"] != self.account:
            raise RuntimeError("AccountMismatch")
        self.path = STATE / "deployment.json"
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {
            "account_id": self.account, "app_region": REGION, "model": "openai.gpt-6-luna",
            "started_at": self.now(), "secret_file": existing["secret_file"],
        }
        if self.data["account_id"] != self.account or self.data["app_region"] != REGION:
            raise RuntimeError("DeploymentScopeMismatch")

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    def client(self, name):
        return self.session.client(name, region_name=REGION, config=self.config)

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
                raise RuntimeError("StackFailed: " + status)
            if attempt % 5 == 0:
                print(json.dumps({"stack": stack["StackName"], "status": status}), flush=True)
            time.sleep(10)
        raise RuntimeError("StackWaitTimeout")

    def create(self, name, template, key, inputs=None):
        if key not in self.data:
            text = (ROOT / template).read_text()
            self.client("cloudformation").validate_template(TemplateBody=text)
            result = self.client("cloudformation").create_stack(
                StackName=name, TemplateBody=text, Parameters=inputs or [],
                Capabilities=["CAPABILITY_IAM"],
                Tags=[{"Key": "Project", "Value": "bma-office-studio"}],
            )
            self.data[key] = result["StackId"]
            self.save()
        return self.wait(self.data[key])

    def bootstrap(self):
        stack = self.create("bma-office-build", "studio/infra/bootstrap.yaml", "bootstrap_stack_id")
        self.data["bootstrap_outputs"] = {row["OutputKey"]: row["OutputValue"] for row in stack["Outputs"]}
        self.save()
        print("Document Studio bootstrap ready.", flush=True)

    def artifacts(self):
        repository = self.data["bootstrap_outputs"]["RuntimeRepositoryUri"]
        if repository != f"{self.account}.dkr.ecr.{REGION}.amazonaws.com/bma-office-runtime":
            raise RuntimeError("RepositoryMismatch")
        image_id = subprocess.check_output(
            ["docker", "image", "inspect", "bma-office-runtime:0.1.0", "--format", "{{.Id}}"], text=True
        ).strip()
        tag = "studio-" + image_id.split(":")[1][:16]
        destination = repository + ":" + tag
        ecr = self.client("ecr")
        auth = ecr.get_authorization_token(registryIds=[self.account])["authorizationData"][0]
        username, password = base64.b64decode(auth["authorizationToken"]).decode().split(":", 1)
        subprocess.run(["docker", "tag", "bma-office-runtime:0.1.0", destination], check=True)
        with tempfile.TemporaryDirectory(prefix="studio-ecr-") as directory:
            subprocess.run(["docker", "--config", directory, "login", "--username", username,
                            "--password-stdin", repository.split("/")[0]],
                           input=password.encode(), check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["docker", "--config", directory, "push", destination], check=True)
        image = ecr.describe_images(registryId=self.account, repositoryName="bma-office-runtime",
                                    imageIds=[{"imageTag": tag}])["imageDetails"][0]
        self.data.update(runtime_image_uri=repository + "@" + image["imageDigest"],
                         runtime_image_tag=tag, local_image_id=image_id)
        path = STATE / "web-function.zip"
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        bucket, key = self.data["bootstrap_outputs"]["CodeBucket"], f"web/{checksum}.zip"
        with path.open("rb") as stream:
            result = self.client("s3").put_object(Bucket=bucket, Key=key, Body=stream,
                                                 ExpectedBucketOwner=self.account, ServerSideEncryption="AES256")
        self.data.update(code_bucket=bucket, code_key=key, code_version_id=result["VersionId"], web_zip_sha256=checksum)
        self.save()
        print("Document Studio image and web artifacts uploaded.", flush=True)

    def main(self):
        token = json.loads((ROOT / self.data["secret_file"]).read_text())["app_access_token"]
        params = {
            "AppRegion": REGION, "BmaModel": self.data["model"],
            "RuntimeImageUri": self.data["runtime_image_uri"],
            "CodeBucket": self.data["code_bucket"], "CodeKey": self.data["code_key"],
            "CodeVersionId": self.data["code_version_id"], "AppAccessToken": token,
        }
        stack = self.create("bma-office-studio", "studio/infra/template.yaml", "main_stack_id",
                            [{"ParameterKey": key, "ParameterValue": value} for key, value in params.items()])
        self.data["outputs"] = {row["OutputKey"]: row["OutputValue"] for row in stack["Outputs"]}
        self.data["stack_status"] = stack["StackStatus"]
        self.save()
        self.inspect()

    def inspect(self):
        output = self.data["outputs"]
        runtime = self.client("bedrock-agentcore-control").get_agent_runtime(
            agentRuntimeId=output["RuntimeArn"].rsplit("/", 1)[1])
        endpoint = self.client("lambda-web").get_web_function_endpoint(
            functionName="bma-office-studio-web", endpointName="studio")
        worker = self.client("lambda").get_function_configuration(FunctionName=output["WorkerArn"])
        self.data.update(runtime_version=runtime["agentRuntimeVersion"], runtime_status=runtime["status"],
                         web_revision=endpoint["revisionWeights"][0]["revisionId"],
                         web_status=endpoint["state"], worker_status=worker["State"])
        self.save()
        print(json.dumps({key: self.data[key] for key in [
            "app_region", "model", "runtime_version", "runtime_status", "web_revision", "web_status", "worker_status"
        ]}, indent=2), flush=True)

    def update(self):
        cf = self.client("cloudformation")
        stack = cf.describe_stacks(StackName=self.data["main_stack_id"])["Stacks"][0]
        if stack["StackName"] != "bma-office-studio":
            raise RuntimeError("UnexpectedUpdateTarget")
        overrides = {"RuntimeImageUri": self.data["runtime_image_uri"], "BmaModel": self.data["model"],
                     "CodeKey": self.data["code_key"], "CodeVersionId": self.data["code_version_id"]}
        params = [{"ParameterKey": row["ParameterKey"], "UsePreviousValue": True}
                  for row in stack["Parameters"] if row["ParameterKey"] not in overrides]
        params += [{"ParameterKey": key, "ParameterValue": value} for key, value in overrides.items()]
        cf.update_stack(StackName=self.data["main_stack_id"],
                        TemplateBody=(ROOT / "studio/infra/template.yaml").read_text(),
                        Parameters=params, Capabilities=["CAPABILITY_IAM"], DisableRollback=False)
        current = self.wait(self.data["main_stack_id"])
        self.data["outputs"] = {row["OutputKey"]: row["OutputValue"] for row in current["Outputs"]}
        self.data["stack_status"] = current["StackStatus"]
        self.save()
        self.inspect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["bootstrap", "artifacts", "main", "inspect", "update"])
    args = parser.parse_args()
    getattr(Deployment(), args.phase)()
