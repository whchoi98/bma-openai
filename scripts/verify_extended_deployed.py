#!/usr/bin/env python3
"""Bounded real Web -> Luna -> Runtime -> MCP validation for the extracted tools."""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

CASES = {
    "network": {
        "language": "ko",
        "prompt": "서울 리전에서 list_vpcs로 VPC를 최대 2개 확인하고 첫 VPC만 get_vpc_topology로 조회해 관계도를 보여줘. "
                  "list_ebs_volumes와 list_ecr_repositories도 각각 최대 2개만 조회해 줘. 이 도구들 이외의 서비스와 지표는 조회하지 마. "
                  "실제 관측과 구성 관계만 설명하고 잘림과 미조회 범위를 알려줘.",
        "required": ["get_account_context", "list_vpcs", "list_ebs_volumes", "list_ecr_repositories"],
        "optional": ["get_vpc_topology"],
    },
    "configuration": {
        "language": "en",
        "prompt": "Inventory only Seoul S3, DynamoDB, ElastiCache, OpenSearch and MSK with the configured limit of 2 per list. "
                  "Use list_s3_buckets, list_dynamodb_tables, list_elasticache_clusters, list_opensearch_domains and list_msk_clusters. "
                  "If S3, DynamoDB or OpenSearch has returned names, use its configuration tool for the first returned resource only. "
                  "Do not read object contents, table items, cache contents, indices, Kafka messages, metrics, logs, costs or other services. "
                  "Report evidence, missing configuration, truncation and unqueried scope; no invented healthy states.",
        "required": ["get_account_context", "list_s3_buckets", "list_dynamodb_tables",
                     "list_elasticache_clusters", "list_opensearch_domains", "list_msk_clusters"],
        "optional": ["get_s3_bucket_configuration", "get_dynamodb_table_configuration",
                     "get_opensearch_domain_configuration"],
    },
    "security": {
        "language": "ko",
        "prompt": "aws-security-posture 절차로 서울 보안 설정을 점검해 줘. list_vpcs에서 반환된 첫 VPC만 "
                  "list_security_groups로 최대 2개 확인하고, list_ebs_volumes와 list_rds_instances도 최대 2개씩만 읽어 줘. "
                  "위 도구 외의 조회, 지표, 비용, 로그는 실행하지 마. security_checks의 pass/fail/unknown을 구분하고 "
                  "구성 기준 결과를 취약점 확정이나 애플리케이션 정상 판정으로 쓰지 마.",
        "required": ["get_account_context", "list_vpcs", "list_ebs_volumes", "list_rds_instances"],
        "optional": ["list_security_groups"],
    },
}
ABSENT_CONFIGURATION = {
    "NoSuchBucketPolicy", "NoSuchPublicAccessBlockConfiguration",
    "ServerSideEncryptionConfigurationNotFoundError",
}


def verify(case_name):
    deployment = json.loads(Path("artifacts/aws-deployment.json").read_text())
    secret = json.loads(Path(deployment["secret_file"]).read_text())["app_access_token"]
    case = CASES[case_name]
    base = deployment["outputs"]["WebUrl"]
    account = deployment["account_id"]
    output = Path(deployment.get("extended_e2e_directory", "artifacts/e2e-extraction"))
    output.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    started = time.monotonic()
    events, final = [], None
    headers = {"Authorization": "Bearer " + secret}
    with httpx.Client(timeout=httpx.Timeout(60, connect=10)) as client:
        context = client.get(base + "/api/context", headers=headers)
        context.raise_for_status()
        context = context.json()
        assert context["account_id"] == account and context["mode"] == "live"
        assert context["model"] == deployment["model"]
        assert context["app_region"] == "us-east-1" and context["target_region"] == "ap-northeast-2"
        assert context["max_resources"] == 2
        with client.stream("POST", base + "/api/chat", headers=headers,
                           json={"prompt": case["prompt"], "language": case["language"]}) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if time.monotonic() - started > 360:
                    raise TimeoutError("Extended validation exceeded 360 seconds")
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                events.append(event)
                if event.get("type") == "tool_result":
                    result = event["result"]
                    print(json.dumps({"case": case_name, "tool": result["tool"], "status": result["status"],
                                      "count": result["count"], "region": result["region"],
                                      "errors": [e["code"] for e in result["errors"]]}), flush=True)
                if event.get("type") == "complete":
                    final = event
        path = output / f"{case_name}-{stamp}.json"
        path.write_text(json.dumps({"context": context, "events": events, "result": final},
                                   ensure_ascii=False, indent=2) + "\n")
        assert final, f"No final result; see {path}"
        assert not final["errors"], final["errors"]
        names = {item["tool"] for item in final["evidence"]}
        assert set(case["required"]) <= names
        assert names <= set(case["required"] + case["optional"])
        evidence = final["evidence"]
        for result in evidence:
            assert result["account_id"] == account and result["region"] == "ap-northeast-2"
            assert result["count"] <= 2 and result["scope"]["max_resources"] == 2
            assert len(result["api_calls"]) <= 31 and not result["permission_denied"]
            assert result["status"] in {"ok", "empty", "partial"}
            assert all(error["code"] in ABSENT_CONFIGURATION for error in result["errors"]), result["errors"]
            for call in result["api_calls"]:
                assert call["region"] == ("us-east-1" if call["service"] == "sts" else "ap-northeast-2")
                assert call.get("request_id"), call
        listed = {item["tool"]: item for item in evidence}
        conditions = {
            "list_vpcs": "get_vpc_topology" if case_name == "network" else "list_security_groups",
            "list_s3_buckets": "get_s3_bucket_configuration",
            "list_dynamodb_tables": "get_dynamodb_table_configuration",
            "list_opensearch_domains": "get_opensearch_domain_configuration",
        }
        for listing, detail in conditions.items():
            if detail in case["optional"] and listed.get(listing, {}).get("data"):
                assert detail in names, f"Missing detail tool {detail}"
        page = client.get(base + "/api/runs?limit=10", headers=headers)
        page.raise_for_status()
        assert any(run["id"] == final["id"] for run in page.json()["runs"])
        saved = client.get(base + "/api/runs/" + final["id"], headers=headers)
        saved.raise_for_status()
        assert saved.json()["evidence"] == final["evidence"]
    summary = {
        "case": case_name, "status": "passed", "run_id": final["id"], "evidence": str(path),
        "elapsed_seconds": round(time.monotonic() - started, 2), "model": final["model"],
        "tools": sorted(names), "response_status": final["status"],
        "configuration_absence": [error for r in evidence for error in r["errors"]],
        "account_display": "*********" + account[-3:],
        "aws_request_ids": len({call["request_id"] for r in evidence for call in r["api_calls"]}),
    }
    (output / f"{case_name}-latest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=CASES, default="network")
    verify(parser.parse_args().case)
