import importlib.util
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[1] / "scripts/deployment_parameters.py"
spec = importlib.util.spec_from_file_location("deployment_parameters", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

ENV = {
    "APP_REGION": "us-east-1", "TARGET_REGION": "ap-northeast-2", "EXPECTED_ACCOUNT_ID": "111122223333",
    "BMA_ECR_URI": "111122223333.dkr.ecr.us-east-1.amazonaws.com/bma-seoul-runtime",
    "BMA_IMAGE_DIGEST": "sha256:" + "a" * 64, "BMA_MODEL": "openai.test-model",
    "APP_ACCESS_TOKEN": "test-token" * 5, "BMA_CODE_BUCKET": "code-bucket", "BMA_CODE_VERSION": "version-1",
}
CONTEXT = {"expected_account_id": "111122223333", "available_model_ids": ["openai.test-model"]}


def test_deployment_parameters_are_bound_to_verified_account():
    values = module.parameters(ENV, CONTEXT, "111122223333")
    image = next(row["ParameterValue"] for row in values if row["ParameterKey"] == "RuntimeImageUri")
    assert image == "111122223333.dkr.ecr.us-east-1.amazonaws.com/bma-seoul-runtime@sha256:" + "a" * 64
    with pytest.raises(ValueError, match="mismatch"):
        module.parameters(ENV, CONTEXT, "999988887777")


@pytest.mark.parametrize("change", [
    {"BMA_ECR_URI": "999988887777.dkr.ecr.us-east-1.amazonaws.com/bma-seoul-runtime"},
    {"BMA_IMAGE_DIGEST": "latest"}, {"BMA_MODEL": "openai.not-discovered"},
    {"TARGET_REGION": "us-east-1"}, {"BMA_CODE_VERSION": "null"}, {"APP_ACCESS_TOKEN": "short"},
])
def test_invalid_deployment_inputs_are_rejected(change):
    with pytest.raises(ValueError):
        module.parameters({**ENV, **change}, CONTEXT, "111122223333")


def test_small_live_limits_and_content_addressed_code_key():
    env = {**ENV, "BMA_CODE_KEY": "web/content-hash.zip", "MAX_RESOURCES": "2",
           "MAX_PAGES": "2", "MAX_METRIC_HOURS": "1", "MAX_DATAPOINTS": "100", "MAX_TURN_SECONDS": "300"}
    values = {row["ParameterKey"]: row["ParameterValue"] for row in module.parameters(env, CONTEXT, "111122223333")}
    assert values["CodeKey"] == "web/content-hash.zip"
    assert values["MaxResources"] == "2"
    assert values["MaxMetricHours"] == "1"
    with pytest.raises(ValueError):
        module.parameters({**env, "MAX_RESOURCES": "1000"}, CONTEXT, "111122223333")
