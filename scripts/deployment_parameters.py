#!/usr/bin/env python3
"""Write a private CloudFormation parameter file after rechecking the deployment account."""
import json
import os
import re
from pathlib import Path

import boto3


def parameters(env, context, actual_account):
    if actual_account != context["expected_account_id"] or env.get("EXPECTED_ACCOUNT_ID") != actual_account:
        raise ValueError("Deployment account mismatch.")
    if env.get("APP_REGION") != "us-east-1" or env.get("TARGET_REGION") != "ap-northeast-2":
        raise ValueError("Deployment Regions must be explicit.")
    repository = env.get("BMA_ECR_URI", "")
    if repository != f"{actual_account}.dkr.ecr.us-east-1.amazonaws.com/bma-seoul-runtime":
        raise ValueError("Use the same-account, us-east-1 bma-seoul-runtime repository.")
    digest = env.get("BMA_IMAGE_DIGEST", "")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise ValueError("An immutable ECR image digest is required.")
    model = env.get("BMA_MODEL", "")
    if not model.startswith("openai.") or model not in context.get("available_model_ids", []):
        raise ValueError("Run preflight.py --list-models and select a listed OpenAI model.")
    token = env.get("APP_ACCESS_TOKEN", "")
    if len(token) < 32:
        raise ValueError("APP_ACCESS_TOKEN must contain at least 32 characters.")
    bucket, version = env.get("BMA_CODE_BUCKET", ""), env.get("BMA_CODE_VERSION", "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket) or not version or version == "null":
        raise ValueError("Provide a versioned deployment object in BMA_CODE_BUCKET.")
    key = env.get("BMA_CODE_KEY", "web/0.1.0.zip")
    if not key.startswith("web/") or len(key) > 1024 or any(ord(c) < 32 for c in key):
        raise ValueError("BMA_CODE_KEY must identify an object under web/.")
    values = {
        "AppRegion": "us-east-1", "TargetRegion": "ap-northeast-2",
        "RuntimeImageUri": repository + "@" + digest, "RuntimeRepositoryName": "bma-seoul-runtime",
        "CodeBucket": bucket, "CodeKey": key, "CodeVersionId": version,
        "BmaModel": model, "AppAccessToken": token,
    }
    backend = env.get("AGENT_BACKEND", "bma")
    if backend not in {"bma", "converse"}:
        raise ValueError("AGENT_BACKEND must be bma or converse.")
    converse_model = env.get("CONVERSE_MODEL", "global.openai.gpt-6-luna")
    if converse_model != "global.openai.gpt-6-luna":
        raise ValueError("Unsupported Converse inference profile.")
    values.update(AgentBackend=backend, ConverseModel=converse_model)
    for variable, parameter, default, minimum, maximum in [
        ("MAX_RESOURCES", "MaxResources", 100, 1, 100),
        ("MAX_PAGES", "MaxPages", 10, 1, 10),
        ("MAX_METRIC_HOURS", "MaxMetricHours", 6, 1, 6),
        ("MAX_DATAPOINTS", "MaxDatapoints", 1440, 1, 1440),
        ("MAX_TURN_SECONDS", "MaxTurnSeconds", 180, 30, 300),
    ]:
        value = int(env.get(variable, default))
        if not minimum <= value <= maximum:
            raise ValueError(f"{variable} is outside deployment limits.")
        values[parameter] = str(value)
    return [{"ParameterKey": key, "ParameterValue": value} for key, value in values.items()]


def main():
    context = json.loads(Path("artifacts/deployment-context.json").read_text())
    actual = boto3.Session().client("sts", region_name="us-east-1").get_caller_identity()["Account"]
    values = parameters(os.environ, context, actual)
    output = Path("artifacts/deploy-parameters.json")
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(values, stream, indent=2)
        stream.write("\n")
    print(f"Wrote {output} with mode 0600. Secret values were not printed.")


if __name__ == "__main__":
    main()
