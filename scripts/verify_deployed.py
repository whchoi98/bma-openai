#!/usr/bin/env python3
"""Verify the selected agent -> Runtime -> MCP path and SSE with bounded live queries."""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

CASES = {
    "inventory": {
        "prompt": "aws-resource-inventory Skill을 사용해 서울 리전 EC2와 RDS 현황을 알려줘. "
                  "각 목록은 도구 상한 2개까지만 조회하고 다른 서비스는 조회하지 마. "
                  "실제 계정·리전·관측 시각·잘림 여부를 표시하고 구성 상태와 앱 정상 여부를 구분해 줘.",
        "required": ["get_account_context", "list_ec2_instances", "list_rds_instances"],
    },
    "ec2-health": {
        "prompt": "aws-service-health Skill을 사용해 서울에서 상태 점검에 실패한 EC2가 있는지 확인해 줘. "
                  "EC2 목록의 첫 최대 2개만 상태 점검하고, 이번에는 지표·알람·다른 서비스는 조회하지 마. "
                  "누락과 잘림을 표시하고 앱 정상 여부를 단정하지 마.",
        "required": ["get_account_context", "list_ec2_instances", "get_ec2_instance_health"],
    },
    "ecs": {
        "prompt": "aws-service-health Skill로 서울 ECS 서비스의 실행 태스크 수와 배포 상태를 확인해 줘. "
                  "클러스터 목록에서 첫 1개만 선택하고 그 클러스터 서비스 최대 2개만 조회해 줘. "
                  "다른 클러스터, 태스크 상세, 지표와 알람은 이번에 조회하지 마. 미조회 범위를 표시해 줘.",
        "required": ["get_account_context", "list_ecs_clusters", "list_ecs_services", "get_ecs_service_health"],
    },
    "lambda": {
        "prompt": "aws-service-health Skill로 서울 Lambda Event Functions 목록을 최대 2개 읽고, "
                  "그중 첫 함수 1개의 구성 상태와 최근 15분 오류·스로틀 지표를 확인해 줘. "
                  "get_lambda_function_health와 get_resource_metrics를 사용하고 "
                  "지표가 없으면 0이나 정상으로 바꾸지 마. 다른 서비스나 로그는 조회하지 마.",
        "required": ["get_account_context", "list_lambda_functions", "get_lambda_function_health", "get_resource_metrics"],
    },
    "alarms": {
        "prompt": "aws-operations-report Skill을 사용해 서울의 ALARM 상태 CloudWatch 알람을 정리해 줘. "
                  "계정 확인 후 ALARM 목록만 도구 상한 2개까지 조회하고, 다른 서비스는 조회하지 마. "
                  "UTC 원본·Asia/Seoul 표시 시각, 근거 API, 잘림과 미조회 범위를 보고서에 포함해 줘.",
        "required": ["get_account_context", "list_cloudwatch_alarms"],
    },
}
ALLOWED_APIS = {
    "sts": {"GetCallerIdentity"}, "ec2": {"DescribeInstances", "DescribeInstanceStatus"},
    "rds": {"DescribeDBInstances"}, "ecs": {"ListClusters", "ListServices", "DescribeServices"},
    "lambda": {"ListFunctions", "GetFunctionConfiguration"},
    "cloudwatch": {"GetMetricData", "DescribeAlarms"},
}


def verify(case_name):
    deployment = json.loads(Path("artifacts/aws-deployment.json").read_text())
    secret = json.loads(Path(deployment["secret_file"]).read_text())["app_access_token"]
    base = deployment["outputs"]["WebUrl"]
    account = deployment["account_id"]
    case = CASES[case_name]
    backend = deployment.get("agent_backend", "bma")
    output = Path(deployment.get("e2e_directory", "artifacts/e2e-converse" if backend == "converse" else "artifacts/e2e"))
    output.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    events, event_times, final = [], [], None
    started = time.monotonic()
    with httpx.Client(timeout=httpx.Timeout(60, connect=10), follow_redirects=False) as client:
        assert client.get(base + "/health").status_code == 200
        assert client.get(base + "/api/context").status_code == 401, "API is not protected"
        headers = {"Authorization": "Bearer " + secret}
        context = client.get(base + "/api/context", headers=headers)
        context.raise_for_status()
        context = context.json()
        assert context["mode"] == "live"
        assert context["account_id"] == account
        assert context["app_region"] == "us-east-1" and context["target_region"] == "ap-northeast-2"
        assert context["max_resources"] == 2 and context["max_metric_hours"] == 1
        assert context["agent_backend"] == backend
        assert context["model"] == deployment["model"]
        expected_scope = "global" if backend == "converse" else "app_region"
        assert context["model_processing_scope"] == expected_scope
        if backend == "converse":
            assert context["agent_backend"] == "converse"
            assert context["model"] == deployment["model"]
            assert context["model_processing_scope"] == "global"
        with client.stream("POST", base + "/api/chat", headers=headers, json={"prompt": case["prompt"]}) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if time.monotonic() - started > 420:
                    raise TimeoutError("E2E verification exceeded 420 seconds")
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                events.append(event)
                event_times.append({"type": event.get("type"), "seconds": round(time.monotonic() - started, 4)})
                if event.get("type") == "tool_result":
                    result = event["result"]
                    print(json.dumps({"case": case_name, "tool": result["tool"], "status": result["status"],
                                      "count": result["count"], "account_display": "*********" + result["account_id"][-3:],
                                      "region": result["region"]}), flush=True)
                if event.get("type") == "complete":
                    final = event
                if event.get("type") == "error":
                    break
        log = {"case": case_name, "started_at": stamp, "elapsed_seconds": round(time.monotonic() - started, 2),
               "context": context, "events": events, "event_times": event_times, "result": final}
        path = output / f"{case_name}-{stamp}.json"
        path.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n")
        if final is None:
            codes = [event.get("code") for event in events if event.get("type") == "error"]
            raise RuntimeError(f"No completed {backend} result. Codes={codes}. Evidence: {path}")
        assert not final.get("errors"), final.get("errors")
        assert final["mode"] == "live" and final["evidence"]
        deltas = [event for event in event_times if event["type"] == "answer_delta"]
        assert deltas, "No streamed model text received"
        completed = next(event["seconds"] for event in event_times if event["type"] == "complete")
        assert deltas[0]["seconds"] < completed
        assert final["model"] == deployment["model"]
        assert final["agent_backend"] == backend
        assert final["model_processing_scope"] == expected_scope
        names = {r["tool"] for r in final["evidence"]}
        assert set(case["required"]) <= names, f"Missing tools: {set(case['required']) - names}"
        assert names <= set(case["required"]), f"Unrequested tools: {names - set(case['required'])}"
        for result in final["evidence"]:
            assert result["account_id"] == account and result["region"] == "ap-northeast-2"
            assert result["mode"] == "live" and not result["permission_denied"] and not result["errors"]
            assert result["status"] in {"ok", "empty", "partial"}
            assert result["scope"]["max_resources"] == 2
            for call in result["api_calls"]:
                assert call["api"] in ALLOWED_APIS[call["service"]]
                assert call["region"] == ("us-east-1" if call["service"] == "sts" else "ap-northeast-2")
                assert call["success"] and call.get("request_id"), "No real AWS request evidence"
            for row in result["data"]:
                if row.get("data_status") == "no_data":
                    assert row["points"] == []
        for format in ["md", "html"]:
            report = client.get(base + f"/api/runs/{final['id']}/report.{format}", headers=headers)
            report.raise_for_status()
            assert "attachment" in report.headers["content-disposition"]
            assert "Asia/Seoul" in report.text and "*********" + account[-3:] in report.text
            assert account not in report.text
            if backend == "converse":
                assert "글로벌" in report.text
            else:
                assert "BMA (us-east-1)" in report.text and deployment["model"] in report.text
            (output / f"{case_name}-{stamp}.{format}").write_text(report.text)
    summary = {
        "case": case_name, "status": "passed", "run_id": final["id"],
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "tools": sorted(names), "response_status": final["status"],
        "evidence": str(path), "account_id": account, "app_region": "us-east-1", "target_region": "ap-northeast-2",
        "agent_backend": backend, "model": context.get("model"),
        "answer_delta_events": len(deltas), "first_answer_seconds": deltas[0]["seconds"] if deltas else None,
    }
    (output / f"{case_name}-latest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({**summary, "account_id": "*********" + account[-3:]}, ensure_ascii=False), flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=list(CASES), default="inventory")
    arguments = parser.parse_args()
    verify(arguments.case)
