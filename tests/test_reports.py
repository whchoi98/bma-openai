from datetime import timedelta

from conftest import NOW


def report_record(inventory, aws):
    aws.stub("ec2").add_response(
        "describe_instances",
        {"Reservations": [{"Instances": [{"InstanceId": "i-0123456789abcdef0", "State": {"Name": "running"}}]}]},
        {"MaxResults": 50},
    )
    first = inventory.invoke("list_ec2_instances")
    aws.identity()
    aws.stub("rds").add_client_error("describe_db_instances", "AccessDenied", expected_params={"MaxRecords": 50})
    second = inventory.invoke("list_rds_instances")
    return {
        "id": "example", "prompt": "<script>alert(1)</script>", "mode": "live",
        "created_at": "2026-10-26T12:00:00Z", "status": "partial",
        "answer": "<img src=x onerror=alert(1)> 관측 사실",
        "evidence": [first, second], "errors": [],
    }


def test_reports_preserve_failure_scope_and_original_utc(inventory, aws):
    from webapp.reports import render_html, render_markdown

    record = report_record(inventory, aws)
    markdown = render_markdown(record)
    html = render_html(record)
    assert "2026-10-26T12:00:00Z" in markdown
    assert "2026-10-26 21:00:00" in markdown
    assert "Asia/Seoul" in markdown
    assert "AccessDenied" in markdown
    assert "DescribeInstances" in markdown
    assert "i-0123456789abcdef0" in markdown
    assert "ap-northeast-2" in markdown and "us-east-1" in markdown
    assert "미조회" in markdown
    assert "애플리케이션" in markdown
    assert "<script>" not in html
    assert "<img" not in html
    assert "&lt;script&gt;" in html
    assert "AccessDenied" in html


def test_no_metric_data_is_an_attention_item(inventory, aws):
    from webapp.reports import attention_items

    aws.stub("cloudwatch").add_response("get_metric_data", {
        "MetricDataResults": [
            {"Id": f"m{i}", "Values": [], "Timestamps": [], "StatusCode": "Complete"} for i in range(4)
        ]})
    result = inventory.invoke("get_resource_metrics", {
        "service": "lambda", "resource_id": "demo",
        "start_time": (NOW - timedelta(hours=1)).isoformat(), "end_time": NOW.isoformat(),
    })
    notes = attention_items([result])
    assert any("데이터 없음" in item for item in notes)
    assert not any("정상" in item for item in notes)
