from __future__ import annotations

import os
import re
from dataclasses import dataclass

SUPPORTED_SERVICES = (
    "ec2", "rds", "ecs", "lambda", "cloudwatch", "vpc", "ebs", "ecr",
    "s3", "dynamodb", "elasticache", "opensearch", "msk",
)
SDK_SERVICES = ("ec2", "rds", "ecs", "lambda", "cloudwatch", "ecr", "s3",
                "dynamodb", "elasticache", "opensearch", "kafka", "sts")
SAMPLE_ACCOUNT = "000000000000"


@dataclass(frozen=True)
class Settings:
    expected_account_id: str
    app_region: str = "us-east-1"
    target_region: str = "ap-northeast-2"
    mode: str = "live"
    max_resources: int = 100
    max_pages: int = 10
    max_metric_hours: int = 6
    max_datapoints: int = 1440
    metric_period_seconds: int = 300
    model_processing_scope: str = "app_region"

    def __post_init__(self):
        if self.app_region != "us-east-1" or self.target_region != "ap-northeast-2":
            raise ValueError("This demo requires APP_REGION=us-east-1 and TARGET_REGION=ap-northeast-2.")
        if self.mode not in {"live", "sample"}:
            raise ValueError("DATA_MODE must be live or sample.")
        if not re.fullmatch(r"\d{12}", self.expected_account_id):
            raise ValueError("EXPECTED_ACCOUNT_ID must be a deployment-verified 12-digit account ID.")
        if self.mode == "sample" and self.expected_account_id != SAMPLE_ACCOUNT:
            raise ValueError("Sample mode must use the synthetic sample account.")
        if self.mode == "live" and self.expected_account_id == SAMPLE_ACCOUNT:
            raise ValueError("The sample account cannot be used in live mode.")
        for field, upper in [
            ("max_resources", 100), ("max_pages", 10), ("max_metric_hours", 6), ("max_datapoints", 1440)
        ]:
            value = getattr(self, field)
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError(f"{field} must be between 1 and {upper}.")
        if self.metric_period_seconds != 300:
            raise ValueError("This demo uses 300-second metric buckets.")
        if self.model_processing_scope not in {"app_region", "global"}:
            raise ValueError("MODEL_PROCESSING_SCOPE must be app_region or global.")

    @classmethod
    def from_env(cls) -> Settings:
        mode = os.getenv("DATA_MODE", "live")
        return cls(
            expected_account_id=SAMPLE_ACCOUNT if mode == "sample" else os.getenv("EXPECTED_ACCOUNT_ID", ""),
            app_region=os.getenv("APP_REGION", "us-east-1"),
            target_region=os.getenv("TARGET_REGION", "ap-northeast-2"),
            mode=mode,
            max_resources=int(os.getenv("MAX_RESOURCES", "100")),
            max_pages=int(os.getenv("MAX_PAGES", "10")),
            max_metric_hours=int(os.getenv("MAX_METRIC_HOURS", "6")),
            max_datapoints=int(os.getenv("MAX_DATAPOINTS", "1440")),
            model_processing_scope=os.getenv("MODEL_PROCESSING_SCOPE", "app_region"),
        )
