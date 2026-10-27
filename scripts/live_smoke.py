#!/usr/bin/env python3
# ruff: noqa: E402
"""Small read-only live probe. Records the actual execution context and incomplete scope."""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aws_inventory.config import Settings
from aws_inventory.engine import AwsInventory
from webapp.reports import render_html, render_markdown


def run(account_file, output):
    saved = json.loads(account_file.read_text())
    settings = Settings(expected_account_id=saved["expected_account_id"], max_resources=2, max_pages=2,
                        max_metric_hours=1, max_datapoints=100)
    inventory = AwsInventory(settings)
    evidence = []

    def query(tool, args=None):
        result = inventory.invoke(tool, args)
        evidence.append(result)
        print(json.dumps({k: result[k] for k in [
            "tool", "account_id", "region", "status", "count", "truncated", "duration_ms"
        ]}), flush=True)
        if result["status"] == "account_mismatch" or any(
            call["api"] == "GetCallerIdentity" and not call["success"] for call in result["api_calls"]
        ):
            raise SystemExit("Execution account could not be verified; further queries stopped.")
        return result

    context = query("get_account_context")
    if context["status"] != "ok":
        raise SystemExit("Account verification failed; no resource APIs were called.")
    ec2 = query("list_ec2_instances")
    if ec2["resource_ids"]:
        query("get_ec2_instance_health", {"instance_ids": ec2["resource_ids"]})
    query("list_rds_instances")
    clusters = query("list_ecs_clusters")
    if clusters["resource_ids"]:
        cluster = clusters["resource_ids"][0]
        services = query("list_ecs_services", {"cluster": cluster})
        if services["resource_ids"]:
            query("get_ecs_service_health", {"cluster": cluster, "services": services["resource_ids"]})
    functions = query("list_lambda_functions")
    if functions["resource_ids"]:
        function = functions["resource_ids"][0]
        query("get_lambda_function_health", {"function_name": function})
        end = datetime.now(timezone.utc)
        query("get_resource_metrics", {
            "service": "lambda", "resource_id": function,
            "start_time": (end - timedelta(minutes=15)).isoformat(), "end_time": end.isoformat(),
        })
    query("list_cloudwatch_alarms", {"state": "ALARM"})
    record = {
        "id": "live-smoke", "mode": "live", "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "prompt": "로컬 AWS 자격증명으로 서비스별 최대 2개, 클러스터 1개, Lambda 1개의 최근 15분 지표를 검증",
        "answer": "이 결과는 로컬 실행 환경의 실제 AWS 제어 API 응답입니다. 배포된 Runtime 역할, Web Function, BMA 추론의 종단 간 검증은 아닙니다.",
        "status": "partial" if any(r["status"] not in {"ok", "empty"} for r in evidence) else "complete",
        "execution_context": "local_credentials_not_deployed_runtime",
        "evidence": evidence, "errors": [],
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "live-smoke.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    (output / "live-smoke.md").write_text(render_markdown(record))
    (output / "live-smoke.html").write_text(render_html(record))
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-file", type=Path, default=Path("artifacts/deployment-context.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts"))
    args = parser.parse_args()
    run(args.account_file, args.output)
