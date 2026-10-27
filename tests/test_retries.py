import io

import boto3
from botocore.awsrequest import AWSResponse
from botocore.stub import Stubber


def test_sdk_stops_after_three_failed_attempts(monkeypatch):
    from aws_inventory.config import Settings
    from aws_inventory.engine import AwsInventory

    session = boto3.Session(aws_access_key_id="testing", aws_secret_access_key="testing")
    engine = AwsInventory(Settings(expected_account_id="111122223333"), session=session)
    sts = Stubber(engine.client("sts"))
    sts.add_response("get_caller_identity", {
        "Account": "111122223333", "Arn": "arn:aws:iam::111122223333:role/test", "UserId": "test"
    }, {})
    calls = []

    class Body(io.BytesIO):
        def stream(self, amt=None, decode_content=False):
            yield self.read()

    def fail(request):
        calls.append(request.url)
        return AWSResponse(request.url, 500, {"x-amzn-ErrorType": "ServiceException"},
                           Body(b'{"message":"upstream failure"}'))

    client = engine.client("lambda")
    monkeypatch.setattr(client._endpoint.http_session, "send", fail)
    monkeypatch.setattr("botocore.endpoint.time.sleep", lambda duration: None)
    with sts:
        result = engine.invoke("list_lambda_functions")
    assert len(calls) == 3
    assert all("ap-northeast-2" in url for url in calls)
    assert result["status"] == "api_error"
    assert result["data"] == []
