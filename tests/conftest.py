from contextlib import ExitStack
from datetime import datetime, timezone

import boto3
import pytest
from botocore.stub import Stubber

ACCOUNT = "111122223333"
NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)


class StubSession:
    """Use real botocore models while preventing every network request."""

    def __init__(self):
        self.session = boto3.Session(
            aws_access_key_id="testing", aws_secret_access_key="testing"
        )
        self.clients = {}
        self.stubbers = {}
        self.regions = []
        self.stack = ExitStack()

    def client(self, name, *, region_name, config=None):
        self.regions.append((name, region_name))
        if name not in self.clients:
            client = self.session.client(name, region_name=region_name, config=config)
            stub = Stubber(client)
            self.stack.enter_context(stub)
            self.clients[name] = client
            self.stubbers[name] = stub
        return self.clients[name]

    def stub(self, name):
        if name not in self.clients:
            self.client(
                name, region_name="us-east-1" if name == "sts" else "ap-northeast-2"
            )
        return self.stubbers[name]

    def identity(self, account=ACCOUNT):
        self.stub("sts").add_response(
            "get_caller_identity",
            {
                "Account": account,
                "Arn": f"arn:aws:sts::{account}:assumed-role/inventory/test",
                "UserId": "TEST:session",
            },
            {},
        )

    def close(self):
        self.stack.close()


@pytest.fixture
def aws():
    session = StubSession()
    yield session
    session.close()


@pytest.fixture
def inventory(aws):
    from aws_inventory.config import Settings
    from aws_inventory.engine import AwsInventory

    aws.identity()
    return AwsInventory(
        Settings(expected_account_id=ACCOUNT),
        session=aws,
        clock=lambda: NOW,
    )
