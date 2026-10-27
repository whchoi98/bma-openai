#!/usr/bin/env python3
"""Exercise all sample questions and report downloads in Chromium; no AWS/model calls."""
import json
import os
import socket
import subprocess
import time
import urllib.request
import zipfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def run():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    environment = {**os.environ, "DATA_MODE": "sample", "APP_ACCESS_TOKEN": "",
                   "AWS_LAMBDA_HTTP_ENDPOINT": f"127.0.0.1:{port}",
                   "APP_REGION": "us-east-1", "TARGET_REGION": "ap-northeast-2"}
    process = subprocess.Popen(["node", "web/index.js"], cwd=ROOT, env=environment,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    output = ROOT / "artifacts"
    output.mkdir(exist_ok=True)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Sample server did not start.")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1440, "height": 1050})
            errors = []
            query_requests = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda request: query_requests.append(request.url)
                    if request.method == "POST" and request.url.endswith("/api/chat") else None)
            page.goto(f"http://127.0.0.1:{port}")
            expect(page.locator("#submit")).to_be_enabled()
            assert "샘플" in page.locator("#mode").inner_text()
            assert page.locator("#account").inner_text() == "*********000"
            expected = [
                ["list_ec2_instances", "list_rds_instances"],
                ["get_ec2_instance_health"],
                ["get_ecs_service_health"],
                ["get_resource_metrics"],
                ["list_cloudwatch_alarms"],
                ["list_vpcs", "get_vpc_topology"],
                ["list_ebs_volumes", "list_ecr_repositories"],
                ["list_s3_buckets", "get_s3_bucket_configuration", "list_dynamodb_tables", "get_dynamodb_table_configuration"],
                ["list_security_groups", "list_ebs_volumes", "list_rds_instances"],
            ]
            for index, tools in enumerate(expected):
                page.locator("[data-prompt]").nth(index).click()
                expect(page.locator("#run-status")).to_have_text("조회 완료")
                trace = page.locator("#trace-body").inner_text()
                assert all(tool in trace for tool in tools)
                if index == 0:
                    page.screenshot(path=str(output / "ui-desktop.png"), full_page=True)
                if index == 3:
                    assert "데이터 없음" in page.locator("#answer").inner_text()
                    assert "Errors: 반환된 버킷의 합계 3" in page.locator("#answer").inner_text()
                if index == 5:
                    expect(page.locator("#resource-insights svg")).to_be_visible()
                    assert page.locator(".graph-node").count() > 1
                    page.locator(".graph-node").first.click()
                    expect(page.locator(".graph-selected")).to_be_visible()
                    page.screenshot(path=str(output / "extraction-topology.png"), full_page=True)
                if index == 8:
                    assert page.locator(".security-fail").count() > 0
                    page.screenshot(path=str(output / "extraction-security.png"), full_page=True)
            page.locator("#prompt").fill("조회 가능한 서울 리전 서비스의 운영 보고서를 작성해 줘")
            page.locator("#submit").click()
            expect(page.locator("#run-status")).to_have_text("조회 완료")
            for format in ["md", "html", "docx", "pptx"]:
                with page.expect_download() as download:
                    page.locator(f"#download-{format}").click()
                download.value.save_as(output / f"sample-report.{format}")
                if format in {"docx", "pptx"}:
                    with zipfile.ZipFile(output / f"sample-report.{format}") as package:
                        assert package.testzip() is None
                        assert "[Content_Types].xml" in package.namelist()
            expect(page.locator("#history-list .history-item").first).to_be_visible()
            requests_before_load = len(query_requests)
            page.locator("#history-list .history-item").filter(has_text="첫 VPC의 관계도").first.click()
            expect(page.locator("#phase")).to_have_text("저장된 결과를 표시합니다.")
            expect(page.locator("#resource-insights svg")).to_be_visible()
            assert len(query_requests) == requests_before_load
            page.locator("#language-toggle").click()
            page.locator("#theme-toggle").click()
            expect(page.locator("html")).to_have_attribute("lang", "en")
            expect(page.locator("html")).to_have_attribute("data-theme", "dark")
            page.locator("[data-prompt-key=exampleConfiguration]").click()
            expect(page.locator("#run-status")).to_have_text("Query complete")
            assert "get_s3_bucket_configuration" in page.locator("#trace-body").inner_text()
            page.screenshot(path=str(output / "extraction-history-english.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            page.reload()
            expect(page.locator("#submit")).to_be_enabled()
            assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=str(output / "ui-mobile.png"), full_page=True)
            assert not errors, errors
            browser.close()
            result = {"questions_passed": 9, "report_downloads": ["md", "html", "docx", "pptx"],
                      "viewports": ["1440x1050", "390x844"], "horizontal_overflow": False, "javascript_errors": errors,
                      "data_mode": "sample", "aws_calls": 0, "model_calls": 0,
                      "history_load_without_query": True, "topology": "passed", "security_checks": "passed",
                      "english_dark_mode": "passed"}
            (output / "browser-check.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result, indent=2))
    finally:
        process.terminate()
        process.wait(timeout=5)


if __name__ == "__main__":
    run()
