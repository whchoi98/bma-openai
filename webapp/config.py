import os
import re
from dataclasses import dataclass

from aws_inventory.config import Settings


@dataclass(frozen=True)
class AppSettings:
    inventory: Settings
    model: str = ""
    runtime_arn: str = ""
    session_role_arn: str = ""
    access_token: str = ""
    state_bucket: str = ""
    max_turn_seconds: int = 180

    def __post_init__(self):
        if not 30 <= self.max_turn_seconds <= 600:
            raise ValueError("MAX_TURN_SECONDS must be between 30 and 600.")
        if self.inventory.mode == "sample":
            return
        account = self.inventory.expected_account_id
        if not re.fullmatch(
            rf"arn:aws:bedrock-agentcore:us-east-1:{account}:runtime/[A-Za-z0-9_-]+", self.runtime_arn
        ):
            raise ValueError("BMA_RUNTIME_ARN must identify the expected account's us-east-1 Runtime.")
        if not re.fullmatch(rf"arn:aws:iam::{account}:role/[A-Za-z0-9_+=,.@/-]+", self.session_role_arn):
            raise ValueError("BMA_SESSION_ROLE_ARN must be a role in the expected account.")
        if not re.fullmatch(r"openai\.[A-Za-z0-9._-]+", self.model):
            raise ValueError("Set BMA_MODEL to a model discovered on the us-east-1 Mantle endpoint.")
        if len(self.access_token) < 32:
            raise ValueError("Live mode requires APP_ACCESS_TOKEN with at least 32 characters.")
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", self.state_bucket):
            raise ValueError("Live mode requires an APP_STATE_BUCKET in us-east-1.")

    @classmethod
    def from_env(cls):
        return cls(
            inventory=Settings.from_env(),
            model=os.getenv("BMA_MODEL", ""),
            runtime_arn=os.getenv("BMA_RUNTIME_ARN", ""),
            session_role_arn=os.getenv("BMA_SESSION_ROLE_ARN", ""),
            access_token=os.getenv("APP_ACCESS_TOKEN", ""),
            state_bucket=os.getenv("APP_STATE_BUCKET", ""),
            max_turn_seconds=int(os.getenv("MAX_TURN_SECONDS", "180")),
        )
