import json

from fastapi.testclient import TestClient


def sample_settings(**kwargs):
    from aws_inventory.config import Settings
    from webapp.config import AppSettings
    return AppSettings(inventory=Settings(expected_account_id="000000000000", mode="sample"), **kwargs)


def parse_events(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_sample_request_produces_evidence_and_downloads():
    from webapp.main import create_app

    with TestClient(create_app(sample_settings())) as client:
        config = client.get("/api/context")
        assert config.json()["mode"] == "sample"
        assert config.json()["app_region"] == "us-east-1"
        assert config.json()["target_region"] == "ap-northeast-2"
        response = client.post("/api/chat", json={"prompt": "상태 점검에 실패한 EC2가 있는지 확인해 줘"})
        assert response.status_code == 200
        events = parse_events(response)
        tools = [event["result"] for event in events if event["type"] == "tool_result"]
        assert {result["tool"] for result in tools} == {
            "get_account_context", "list_ec2_instances", "get_ec2_instance_health"
        }
        done = events[-1]
        assert done["type"] == "complete"
        assert done["mode"] == "sample"
        run_id = done["id"]
        assert client.get(f"/api/runs/{run_id}/report.md").status_code == 200
        report = client.get(f"/api/runs/{run_id}/report.html")
        assert report.status_code == 200
        assert "attachment" in report.headers["content-disposition"]
        assert "샘플" in report.text


def test_browser_cannot_override_account_mode_region_or_runtime():
    from webapp.main import create_app

    with TestClient(create_app(sample_settings())) as client:
        assert client.post("/api/chat", json={"prompt": "EC2", "account_id": "999988887777"}).status_code == 422
        assert client.post("/api/chat", json={"prompt": "EC2", "mode": "live"}).status_code == 422
        assert client.post("/api/chat", json={"prompt": ""}).status_code == 422
        assert client.post("/api/chat", json={"prompt": "x" * 4001}).status_code == 422


def test_all_api_paths_require_configured_access_key():
    from webapp.main import create_app

    with TestClient(create_app(sample_settings(access_token="test-access-token"))) as client:
        assert client.get("/").status_code == 200
        assert client.get("/health").status_code == 200
        assert client.get("/api/context").status_code == 401
        assert client.post("/api/chat", json={"prompt": "EC2"}).status_code == 401
        assert client.get("/api/runs/unknown/report.md").status_code == 401
        assert client.get("/api/context", headers={"Authorization": "Bearer test-access-token"}).status_code == 200


def test_sample_queries_only_requested_services():
    from webapp.main import create_app

    with TestClient(create_app(sample_settings())) as client:
        events = parse_events(client.post("/api/chat", json={"prompt": "서울 리전 EC2와 RDS 현황을 알려줘"}))
        tools = [e["result"]["tool"] for e in events if e["type"] == "tool_result"]
        assert tools == ["get_account_context", "list_ec2_instances", "list_rds_instances"]


def test_sample_does_not_silently_switch_to_aws():
    from webapp.main import create_app

    with TestClient(create_app(sample_settings())) as client:
        response = client.post("/api/chat", json={"prompt": "S3 버킷을 삭제해 줘"})
        events = parse_events(response)
        assert not any(e["type"] == "tool_result" and e["result"]["service"] != "sts" for e in events)
        assert "지원" in events[-1]["answer"]
