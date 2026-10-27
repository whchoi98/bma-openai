#!/usr/bin/env python3
"""Bounded live proof of BMA continuation, reconnect and prior-evidence reuse."""
import io
import json
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import boto3
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest


def verify():
    deployment = json.loads(Path("artifacts/aws-deployment.json").read_text())
    account = deployment["account_id"]
    token = json.loads(Path(deployment["secret_file"]).read_text())["app_access_token"]
    base = deployment["outputs"]["WebUrl"]
    output = Path("artifacts/investigations/live")
    output.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": "Bearer " + token}
    aws = boto3.Session()
    assert aws.client("sts", region_name="us-east-1").get_caller_identity()["Account"] == account
    s3 = aws.client("s3", region_name="us-east-1")
    investigation_id = str(uuid.uuid4())
    records, snapshots, private_turns = [], [], []
    started = time.monotonic()

    def request(method, path, body=None):
        with httpx.Client(timeout=45) as client:
            response = client.request(method, base + path, headers=headers,
                                      **({"json": body} if body is not None else {}))
        response.raise_for_status()
        return response

    def private(kind, identifier):
        key = f"investigations/{account}/ap-northeast-2/{kind}/{identifier}.json"
        body = s3.get_object(Bucket=deployment["outputs"]["StateBucket"], Key=key,
                             ExpectedBucketOwner=account)["Body"].read(4_000_001)
        assert len(body) <= 4_000_000
        return json.loads(body)

    def public_keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                assert key not in {"bma_session_id", "bma_turn_id", "worker_token", "lease_until", "submission_text"}
                public_keys(item)
        elif isinstance(value, list):
            for item in value:
                public_keys(item)

    def wait_for_result(run_id):
        events, final, deadline = [], None, time.monotonic() + 350
        with httpx.Client(timeout=httpx.Timeout(40, connect=10)) as client:
            with client.stream("GET", base + f"/api/investigations/{investigation_id}/turns/{run_id}/events",
                               headers=headers) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if time.monotonic() > deadline:
                        raise TimeoutError("Investigation validation deadline")
                    if not line.startswith("data: "):
                        continue
                    event = json.loads(line[6:])
                    public_keys(event)
                    events.append(event)
                    if event["type"] == "snapshot":
                        state = event["run"]
                        print(json.dumps({"run": run_id, "status": state["status"], "phase": state["phase"],
                                          "tools": len(state["evidence"])}), flush=True)
                    if event["type"] == "complete":
                        final = event
                    if event["type"] == "error":
                        raise RuntimeError(event["code"])
        (output / f"{run_id}.json").write_text(json.dumps(events, ensure_ascii=False, indent=2) + "\n")
        assert final, "No final report was delivered"
        assert final["status"] in {"complete", "partial"} and not final["errors"], final.get("errors")
        assert final["model"] == "openai.gpt-6-luna" and final["agent_backend"] == "bma"
        assert final["app_region"] == "us-east-1" and final["target_region"] == "ap-northeast-2"
        assert final["procedure"]["id"] == "service-health"
        for evidence in final["evidence"]:
            assert evidence["account_id"] == account and evidence["region"] == "ap-northeast-2"
            assert not evidence["permission_denied"] and not evidence["errors"]
            assert all(call.get("request_id") for call in evidence["api_calls"])
        records.append(final)
        snapshots.extend(events)
        private_turns.append(private("turns", run_id))
        return final

    catalog = request("GET", "/api/procedures").json()
    assert catalog["enabled"] is True and len(catalog["procedures"]) == 4
    question = {
        "request_id": investigation_id, "procedure_id": "service-health", "language": "ko",
        "prompt": "서울 EC2 목록만 최대 2개 조회해 줘. 계정 확인 후 list_ec2_instances만 호출하고 "
                  "지금은 상태 점검, 지표, 알람, 다른 서비스를 조회하지 마. 관측 시각과 잘림을 표시해 줘.",
    }
    created = request("POST", "/api/investigations", question).json()
    repeated = request("POST", "/api/investigations", question).json()
    assert created["investigation"]["id"] == repeated["investigation"]["id"] == investigation_id
    assert len(repeated["investigation"]["turns"]) == 1
    # Deliberately drop the first subscription. A new HTTP connection must recover
    # the same persisted job, rather than submitting another model request.
    with httpx.Client(timeout=30) as client:
        with client.stream("GET", base + f"/api/investigations/{investigation_id}/turns/{investigation_id}/events",
                           headers=headers) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line.startswith("data: "):
                    assert json.loads(line[6:])["type"] == "snapshot"
                    break
    first = wait_for_result(investigation_id)
    assert {item["tool"] for item in first["evidence"]} == {"get_account_context", "list_ec2_instances"}
    initial_session = private("sessions", investigation_id)["bma_session_id"]

    second_id = str(uuid.uuid4())
    request("POST", f"/api/investigations/{investigation_id}/turns", {
        "request_id": second_id, "language": "en",
        "prompt": "Summarize the EC2 observations already collected in this investigation in English. "
                  "Use only prior evidence, preserve its original observation time and identify it as reused. "
                  "Do not call resource APIs, metrics, alarms, or list EC2 again.",
    })
    second = wait_for_result(second_id)
    assert second["evidence_reused"] is True
    assert investigation_id in second["source_run_ids"]
    assert "Previously observed evidence" in second["answer"]
    old_times = {item["observed_at"] for item in first["evidence"] if item["service"] != "sts"}
    assert {item["observed_at"] for item in second["evidence"] if item["service"] != "sts"} == old_times

    third_id = str(uuid.uuid4())
    request("POST", f"/api/investigations/{investigation_id}/turns", {
        "request_id": third_id, "language": "ko",
        "prompt": "이 조사에서 이미 조회한 EC2 중 첫 번째 인스턴스 한 개만 현재 상태 점검을 확인해 줘. "
                  "계정 확인과 get_ec2_instance_health만 호출해. EC2 목록 재조회, 지표, 알람과 다른 서비스는 "
                  "호출하지 마. 이전 대화에 나온 실제 인스턴스 ID만 사용해.",
    })
    third = wait_for_result(third_id)
    names = {item["tool"] for item in third["evidence"]}
    assert names <= {"get_account_context", "get_ec2_instance_health"} and "get_ec2_instance_health" in names
    original_ids = next(item["resource_ids"] for item in first["evidence"] if item["tool"] == "list_ec2_instances")
    health_ids = next(item["resource_ids"] for item in third["evidence"] if item["tool"] == "get_ec2_instance_health")
    assert health_ids and set(health_ids) <= set(original_ids) and len(health_ids) == 1

    saved = private("sessions", investigation_id)
    assert saved["bma_session_id"] == initial_session
    assert len(saved["turns"]) == 3 and saved["active_run_id"] is None
    assert len({turn["bma_turn_id"] for turn in private_turns}) == 3
    assert len({record["procedure"]["sha256"] for record in records}) == 1
    url = f"https://bedrock-mantle.us-east-1.api.aws/openai/v1/agents/sessions/{initial_session}/items?limit=100&order=asc"
    signed = AWSRequest(method="GET", url=url)
    SigV4Auth(aws.get_credentials().get_frozen_credentials(), "bedrock-mantle", "us-east-1").add_auth(signed)
    response = httpx.get(url, headers=dict(signed.headers), timeout=30)
    response.raise_for_status()
    items = response.json()
    assert not items["has_more"]
    second_tools = [item["name"] for item in items["data"]
                    if item.get("turn_id") == private_turns[1]["bma_turn_id"] and item.get("type") == "mcp_call"]
    assert set(second_tools) <= {"get_account_context"}, second_tools
    for format in ["md", "html", "docx", "pptx"]:
        report = request("GET", f"/api/runs/{second_id}/report.{format}")
        (output / f"reused-report.{format}").write_bytes(report.content)
        if format in {"docx", "pptx"}:
            with zipfile.ZipFile(io.BytesIO(report.content)) as archive:
                assert archive.testzip() is None
                text = "\n".join(archive.read(name).decode() for name in archive.namelist() if name.endswith(".xml"))
        else:
            text = report.text
        assert account not in text and "Previously observed evidence" in text
    proof = {
        "status": "passed", "verified_at": datetime.now(timezone.utc).isoformat(),
        "investigation_id": investigation_id, "run_ids": [record["id"] for record in records],
        "same_bma_session": True, "distinct_bma_turns": 3, "idempotent_create": True,
        "reconnect_without_resubmission": True, "previous_observation_time_preserved": True,
        "summary_resource_api_calls": 0, "followup_uses_observed_instance": True,
        "model": deployment["model"], "procedure_version": "1.0.0",
        "snapshot_count": len(snapshots), "elapsed_seconds": round(time.monotonic() - started, 2),
        "report_formats": ["md", "html", "docx", "pptx"],
    }
    (output / "summary.json").write_text(json.dumps(proof, indent=2) + "\n")
    print(json.dumps(proof, indent=2), flush=True)


if __name__ == "__main__":
    verify()
