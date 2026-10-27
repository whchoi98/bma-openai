#!/usr/bin/env python3
"""Read-only deployment account/model discovery. No infrastructure is created."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import boto3
import botocore
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.config import Config


def preflight(output, *, list_models=False):
    session = boto3.Session()
    config = Config(connect_timeout=3, read_timeout=10, retries={"mode": "standard", "total_max_attempts": 3})
    actual = session.client("sts", region_name="us-east-1", config=config).get_caller_identity()["Account"]
    if output.exists():
        saved = json.loads(output.read_text())
        if saved.get("expected_account_id") != actual:
            raise SystemExit("Deployment account changed; existing expected-account record was not overwritten.")
    result = {
        "expected_account_id": actual, "app_region": "us-east-1", "target_region": "ap-northeast-2",
        "verified_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "verification_api": "STS.GetCallerIdentity", "botocore_version": botocore.__version__,
    }
    # Fail early on SDKs that conflate or do not support the separate service models.
    assert "ListWebFunctions" in session._session.get_service_model("lambda-web").operation_names
    assert "ListFunctions" in session._session.get_service_model("lambda").operation_names
    model = session._session.get_service_model("bedrock-agentcore-control")
    assert "platformVersion" in model.operation_model("CreateAgentRuntime").input_shape.members
    if list_models:
        url = "https://bedrock-mantle.us-east-1.api.aws/v1/models"
        request = AWSRequest(method="GET", url=url)
        SigV4Auth(session.get_credentials().get_frozen_credentials(), "bedrock-mantle", "us-east-1").add_auth(request)
        try:
            response = httpx.get(url, headers=dict(request.headers), timeout=15)
            if response.is_success:
                result["available_model_ids"] = [row["id"] for row in response.json().get("data", [])[:100]]
            else:
                result["model_discovery_error"] = f"HTTP{response.status_code}"
        except httpx.HTTPError:
            result["model_discovery_error"] = "NetworkError"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/deployment-context.json"))
    parser.add_argument("--list-models", action="store_true", help="Read the regional model catalog; does not invoke a model.")
    args = parser.parse_args()
    print(json.dumps(preflight(args.output, list_models=args.list_models), indent=2))
