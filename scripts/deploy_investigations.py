#!/usr/bin/env python3
"""Update only the existing Virginia demo with reviewed investigation resources."""
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.config import Config

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "artifacts/investigations"
REGION = "us-east-1"


def deploy():
    manifest_path = ROOT / "artifacts/aws-deployment.json"
    deployment = json.loads(manifest_path.read_text())
    account = deployment["account_id"]
    session = boto3.Session()
    config = Config(connect_timeout=4, read_timeout=30,
                    retries={"mode": "standard", "total_max_attempts": 3})
    client = lambda name: session.client(name, region_name=REGION, config=config)
    if client("sts").get_caller_identity()["Account"] != account:
        raise RuntimeError("AccountMismatch")
    if (deployment["app_region"], deployment["target_region"], deployment["agent_backend"],
            deployment["model"]) != (REGION, "ap-northeast-2", "bma", "openai.gpt-6-luna"):
        raise RuntimeError("UnexpectedDeploymentScope")
    cf = client("cloudformation")
    changes = []

    def update(stack_id, template_name, overrides, allowed):
        stack = cf.describe_stacks(StackName=stack_id)["Stacks"][0]
        parameters = [
            {"ParameterKey": row["ParameterKey"], "UsePreviousValue": True}
            for row in stack["Parameters"] if row["ParameterKey"] not in overrides
        ] + [{"ParameterKey": key, "ParameterValue": value} for key, value in overrides.items()]
        template = (ROOT / template_name).read_text()
        cf.validate_template(TemplateBody=template)
        suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        result = cf.create_change_set(
            StackName=stack_id, ChangeSetName="investigations-" + suffix, ChangeSetType="UPDATE",
            TemplateBody=template, Parameters=parameters, Capabilities=["CAPABILITY_IAM"],
            Description="Add bounded BMA investigation worker, state and UI.",
        )
        change_id = result["Id"]
        for _ in range(60):
            detail = cf.describe_change_set(ChangeSetName=change_id)
            if detail["Status"] == "CREATE_COMPLETE":
                break
            if detail["Status"] == "FAILED":
                if "didn't contain changes" in detail.get("StatusReason", ""):
                    return stack
                raise RuntimeError("ChangeSetFailed: " + detail.get("StatusReason", ""))
            time.sleep(3)
        else:
            raise RuntimeError("ChangeSetTimeout")
        rows = [row["ResourceChange"] for row in detail["Changes"]]
        (STATE / f"{stack['StackName']}-change-set.json").write_text(
            json.dumps(rows, indent=2, default=str) + "\n"
        )
        for row in rows:
            name = row["LogicalResourceId"]
            if name not in allowed or row["Action"] == "Remove":
                raise RuntimeError("UnexpectedResourceChange: " + name)
            if row.get("Replacement") in {"True", "Conditional"} and name != "WebRevision":
                raise RuntimeError("UnexpectedReplacement: " + name)
        changes.extend({"stack": stack["StackName"], "resource": row["LogicalResourceId"],
                        "action": row["Action"], "replacement": row.get("Replacement", "False")} for row in rows)
        print(json.dumps({"stack": stack["StackName"], "reviewed_changes": changes}), flush=True)
        cf.execute_change_set(ChangeSetName=change_id, DisableRollback=False)
        for attempt in range(120):
            time.sleep(8)
            current = cf.describe_stacks(StackName=stack_id)["Stacks"][0]
            status = current["StackStatus"]
            if status == "UPDATE_COMPLETE":
                return current
            if "FAILED" in status or "ROLLBACK" in status:
                events = cf.describe_stack_events(StackName=stack_id)["StackEvents"]
                (STATE / "deployment-failure.json").write_text(json.dumps(events, indent=2, default=str) + "\n")
                raise RuntimeError("StackUpdateFailed: " + status)
            if attempt % 5 == 0:
                print(json.dumps({"stack": stack["StackName"], "status": status}), flush=True)
        raise RuntimeError("StackUpdateTimeout")

    update(deployment["bootstrap_stack_id"], "infra/bootstrap.yaml", {
        "InvestigationWorkerFunctionName": "bma-seoul-inventory-investigation-worker",
    }, {"CodeBucketTls"})
    zip_path = ROOT / "artifacts/web-function.zip"
    with zip_path.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    code_key = f"web/{checksum}.zip"
    with zip_path.open("rb") as stream:
        uploaded = client("s3").put_object(
            Bucket=deployment["code_bucket"], Key=code_key, Body=stream,
            ExpectedBucketOwner=account, ServerSideEncryption="AES256",
        )
    main = update(deployment["main_stack_id"], "infra/template.yaml", {
        "CodeKey": code_key, "CodeVersionId": uploaded["VersionId"],
    }, {"AppState", "AppStateTls", "WebRole", "WebRevision", "WebEndpoint", "WorkerRole", "WorkerLogs",
        "InvestigationWorker", "InvestigationWorkerAsync"})
    outputs = {row["OutputKey"]: row["OutputValue"] for row in main["Outputs"]}
    endpoint = client("lambda-web").get_web_function_endpoint(
        functionName="bma-seoul-inventory-web", endpointName="demo"
    )
    worker = client("lambda").get_function_configuration(FunctionName=outputs["InvestigationWorkerArn"])
    runtime = client("bedrock-agentcore-control").get_agent_runtime(
        agentRuntimeId=outputs["RuntimeArn"].rsplit("/", 1)[1]
    )
    if str(runtime["agentRuntimeVersion"]) != str(deployment["runtime_version"]):
        raise RuntimeError("UnexpectedRuntimeVersionChange")
    if endpoint["state"] != "Active" or worker["State"] != "Active":
        raise RuntimeError("DeploymentNotActive")
    proof = {
        "status": "deployed", "deployed_at": datetime.now(timezone.utc).isoformat(),
        "app_region": REGION, "target_region": "ap-northeast-2", "model": deployment["model"],
        "changes": changes, "web_revision": endpoint["revisionWeights"][0]["revisionId"],
        "worker_name": worker["FunctionName"], "worker_runtime": worker["Runtime"],
        "worker_timeout": worker["Timeout"], "worker_memory": worker["MemorySize"],
        "worker_code_sha256": worker["CodeSha256"], "runtime_version": runtime["agentRuntimeVersion"],
        "web_zip_sha256": checksum,
    }
    (STATE / "deployment.json").write_text(json.dumps(proof, indent=2) + "\n")
    deployment.update(
        outputs=outputs, stack_status=main["StackStatus"], web_revision=proof["web_revision"],
        code_key=code_key, code_version_id=uploaded["VersionId"], web_zip_sha256=checksum,
        investigation_worker_arn=outputs["InvestigationWorkerArn"],
        investigations_status="deployed", investigations_deployed_at=proof["deployed_at"],
    )
    manifest_path.write_text(json.dumps(deployment, indent=2) + "\n")
    print(json.dumps(proof, indent=2), flush=True)


if __name__ == "__main__":
    deploy()
