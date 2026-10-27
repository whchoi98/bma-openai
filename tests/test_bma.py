import json

import boto3
import httpx
import pytest
from conftest import ACCOUNT

RUNTIME = f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:runtime/seoul_tools-1234567890"
ROLE = f"arn:aws:iam::{ACCOUNT}:role/BmaSeoulSession"


def app_settings(**overrides):
    from aws_inventory.config import Settings
    from webapp.config import AppSettings

    return AppSettings(
        inventory=Settings(expected_account_id=ACCOUNT),
        model="openai.test-model",
        runtime_arn=RUNTIME,
        session_role_arn=ROLE,
        access_token="a" * 40,
        state_bucket="example-state",
        **overrides,
    )


def test_bma_request_uses_west_region_stdio_and_explicit_allowlist():
    from webapp.bma import BmaClient

    captured = []

    def handle(request):
        captured.append(request)
        return httpx.Response(200, json={"id": "session_opaque"})

    session = boto3.Session(aws_access_key_id="testing", aws_secret_access_key="testing")
    client = BmaClient(app_settings(), aws_session=session, transport=httpx.MockTransport(handle))
    assert client.create_session("서울 EC2 조회") == "session_opaque"
    request = captured[0]
    assert request.url.host == "bedrock-mantle.us-east-1.api.aws"
    assert "/us-east-1/bedrock-mantle/aws4_request" in request.headers["authorization"]
    body = json.loads(request.content)
    assert body["environment"]["type"] == "aws_bedrock_agentcore"
    assert body["environment"]["runtime_arn"] == RUNTIME
    assert body["environment"]["capability_directories"] == ["/opt/bma/skills"]
    assert body["role_arn"] == ROLE
    tool = body["agent"]["tools"][0]
    assert tool["transport"]["type"] == "stdio"
    assert tool["transport"]["command"] == "/opt/bma/venv/bin/python"
    assert "TARGET_REGION" in tool["transport"]["env_vars"]
    assert "APP_REGION" in tool["transport"]["env_vars"]
    assert "EXPECTED_ACCOUNT_ID" in tool["transport"]["env_vars"]
    assert "env" not in tool["transport"]
    assert tool["required"] is True
    assert "get_ec2_instance_health" in tool["allowed_tools"]
    assert len(tool["allowed_tools"]) == 24
    assert "execute_aws_cli" not in tool["allowed_tools"]


def test_wrong_runtime_region_or_account_cannot_enter_session_config():
    from aws_inventory.config import Settings
    from webapp.config import AppSettings

    with pytest.raises(ValueError):
        AppSettings(
            inventory=Settings(expected_account_id=ACCOUNT), model="openai.test",
            runtime_arn=RUNTIME.replace("us-east-1", "ap-northeast-2"), session_role_arn=ROLE,
            access_token="a" * 40, state_bucket="example-state"
        )


def test_no_automatic_retry_for_ambiguous_session_creation():
    from webapp.bma import BmaClient, BmaError

    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(503, text="raw-upstream-secret")

    client = BmaClient(
        app_settings(), aws_session=boto3.Session(aws_access_key_id="testing", aws_secret_access_key="testing"),
        transport=httpx.MockTransport(handle),
    )
    with pytest.raises(BmaError) as error:
        client.create_session("hello")
    assert len(requests) == 1
    assert "raw-upstream-secret" not in str(error.value)


def test_items_pagination_is_bounded_and_preserves_partial(monkeypatch):
    from webapp.bma import BmaClient

    requests = []

    def handle(request):
        requests.append(request)
        if request.url.params.get("after") == "first":
            return httpx.Response(200, json={"data": [{"id": "second", "type": "reasoning"}], "has_more": False})
        return httpx.Response(200, json={"data": [{"id": "first", "type": "reasoning"}], "has_more": True, "last_id": "first"})

    client = BmaClient(
        app_settings(), aws_session=boto3.Session(aws_access_key_id="testing", aws_secret_access_key="testing"),
        transport=httpx.MockTransport(handle),
    )
    items, complete = client.list_items("session_1")
    assert len(items) == 2
    assert complete is True
    assert len(requests) == 2


def test_sse_multiline_and_unknown_events_are_parsed():
    from webapp.bma import parse_sse

    events = list(parse_sse([
        ": keep-alive", "", "event: agent.session.turn.completed",
        'data: {"type":', 'data: "agent.session.turn.completed"}', "",
    ]))
    assert events[-1]["type"] == "agent.session.turn.completed"


def test_stream_headers_match_the_sigv4_signature(monkeypatch):
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
    from botocore.credentials import Credentials
    from conftest import NOW

    from webapp.bma import BmaClient

    monkeypatch.setattr("botocore.auth.get_current_datetime", lambda **kwargs: NOW.replace(tzinfo=None))

    def handle(request):
        assert request.url.params.get("stream") == "true"
        auth = request.headers["authorization"]
        names = auth.split("SignedHeaders=")[1].split(",")[0].split(";")
        signed = AWSRequest(method="GET", url=str(request.url), data=b"",
                            headers={name: request.headers[name] for name in names})
        SigV4Auth(Credentials("testing", "testing"), "bedrock-mantle", "us-east-1").add_auth(signed)
        assert auth == signed.headers["Authorization"]
        return httpx.Response(
            200, text='data: {"type":"agent.session.turn.completed"}\n\n',
            headers={"content-type": "text/event-stream"},
        )

    client = BmaClient(
        app_settings(), aws_session=boto3.Session(aws_access_key_id="testing", aws_secret_access_key="testing"),
        transport=httpx.MockTransport(handle),
    )
    assert list(client.events("session_1"))[-1]["type"] == "agent.session.turn.completed"


def test_ui_filters_reasoning_commands_and_non_final_messages():
    from webapp.evidence import public_items

    items = [
        {"id": "r", "type": "reasoning", "summary": "INTERNAL-REASONING"},
        {"id": "c", "type": "command_execution", "command": "secret-command", "output": "SECRET"},
        {"id": "a", "type": "message", "role": "assistant", "channel": "analysis",
         "content": [{"type": "output_text", "text": "INTERNAL-ANALYSIS"}]},
        {"id": "m", "type": "message", "role": "assistant",
         "content": [{"type": "output_text", "text": "관측한 결과입니다."}]},
    ]
    result = public_items(items, app_settings().inventory)
    assert result["answer"] == "관측한 결과입니다."
    assert result["evidence"] == []
    assert "INTERNAL" not in json.dumps(result)
    assert "SECRET" not in json.dumps(result)


def test_only_expected_mcp_server_results_become_evidence(inventory, aws):
    from webapp.evidence import public_items

    aws.stub("ec2").add_response("describe_instances", {"Reservations": []}, {"MaxResults": 50})
    output = inventory.invoke("list_ec2_instances")
    items = [
        {"id": "good", "type": "mcp_call", "server_label": "seoul_aws", "name": "list_ec2_instances",
         "output": json.dumps(output), "status": "completed"},
        {"id": "bad", "type": "mcp_call", "server_label": "other", "name": "execute",
         "output": "private-data", "status": "completed"},
    ]
    result = public_items(items, inventory.settings)
    assert len(result["evidence"]) == 1
    assert result["evidence"][0]["item_id"] == "good"
    assert result["evidence"][0]["status"] == "empty"
    assert "private-data" not in json.dumps(result)


def test_mismatched_evidence_is_rejected(inventory, aws):
    from webapp.evidence import public_items

    aws.stub("ec2").add_response("describe_instances", {"Reservations": []}, {"MaxResults": 50})
    output = inventory.invoke("list_ec2_instances")
    output["account_id"] = "999988887777"
    result = public_items([
        {"id": "foreign", "type": "mcp_call", "server_label": "seoul_aws",
         "name": "list_ec2_instances", "output": json.dumps(output)}
    ], inventory.settings)
    assert result["evidence"] == []
    assert result["evidence_errors"] == ["EvidenceAccountMismatch"]


def test_bma_result_wrapper_with_structured_content_is_supported(inventory):
    from webapp.evidence import public_items

    context = inventory.invoke("get_account_context")
    result = public_items([
        {"id": "ctx", "type": "mcp_call", "server_label": "seoul_aws", "name": "get_account_context",
         "result": {"structuredContent": context, "content": []}}
    ], inventory.settings)
    assert result["evidence"][0]["data"][0]["account_verified"] is True
