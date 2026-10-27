import html
import json
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from aws_inventory.config import SUPPORTED_SERVICES

STATUS_TEXT = {
    "ok": "조회 성공", "empty": "조회 성공 · 데이터 없음", "partial": "일부 결과",
    "access_denied": "접근 권한 없음", "api_error": "API 호출 실패",
    "unsupported_service": "미지원 서비스", "account_mismatch": "계정 불일치 · 차단",
    "invalid_input": "입력 범위 오류",
}


def kst(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            ZoneInfo("Asia/Seoul")
        ).strftime("%Y-%m-%d %H:%M:%S %Z")
    except (ValueError, TypeError, AttributeError):
        return "시각 확인 불가"


def attention_items(evidence):
    notes = []
    for result in evidence:
        prefix = f"{result['service']} / {result['tool']}"
        if result["status"] not in {"ok", "empty"}:
            codes = ", ".join(e.get("code", "Unknown") for e in result.get("errors", []))
            notes.append(f"{prefix}: {STATUS_TEXT.get(result['status'], result['status'])}"
                         + (f" ({codes})" if codes else ""))
        if result.get("truncated"):
            notes.append(f"{prefix}: 조회 한도로 결과가 잘렸습니다.")
        if result.get("missing_resource_ids"):
            notes.append(f"{prefix}: 응답에 포함되지 않은 ID — {', '.join(result['missing_resource_ids'])}")
        for row in result.get("data", []):
            resource = row.get("id") or row.get("resource_id") or ""
            if row.get("data_status") == "no_data":
                notes.append(f"{resource} / {row.get('metric_name')}: 데이터 없음. 호출 부재나 지표 수집 여부를 추가 확인합니다.")
            if any(row.get(key) == "impaired" for key in ["instance_status", "system_status", "attached_ebs_status"]):
                notes.append(f"{resource}: EC2 상태 점검에서 impaired가 관측됐습니다. 애플리케이션 영향은 별도 확인이 필요합니다.")
            desired, running = row.get("desired_count"), row.get("running_count")
            if isinstance(desired, int) and isinstance(running, int) and running < desired:
                notes.append(f"{resource}: 실행 태스크 {running}개 / 목표 {desired}개. 배포 상태와 서비스 영향을 추가 확인합니다.")
            if row.get("state") == "ALARM":
                notes.append(f"{resource}: CloudWatch ALARM 상태가 관측됐습니다.")
            if row.get("metric_name") in {"Errors", "Throttles"} and row.get("points"):
                total = sum(p["value"] for p in row["points"])
                if total > 0:
                    notes.append(f"{resource} / {row['metric_name']}: 반환된 버킷의 관측 합계 {total:g}. "
                                 "수집 구간과 결측 여부를 함께 확인합니다.")
    return list(dict.fromkeys(notes))


def summarize(evidence):
    lines = []
    for result in evidence:
        if result["service"] == "sts":
            continue
        label = STATUS_TEXT.get(result["status"], result["status"])
        count = result.get("resource_count", 0)
        states = Counter(row["state"] for row in result.get("data", []) if row.get("state"))
        line = f"- {result['service']} / {result['tool']}: {label}, 응답에 포함된 리소스 {count}개"
        if states:
            line += " (" + ", ".join(f"{state} {n}개" for state, n in states.items()) + ")"
        if "datapoint_count" in result:
            line += f", 지표 데이터 포인트 {result['datapoint_count']}개"
            metrics = []
            for row in result["data"]:
                if row["data_status"] == "no_data":
                    metrics.append(f"{row['metric_name']}: 데이터 없음")
                elif row["points"] and row["statistic"] == "Sum":
                    metrics.append(f"{row['metric_name']}: 반환된 버킷의 합계 {sum(p['value'] for p in row['points']):g}")
                elif row["points"]:
                    metrics.append(f"{row['metric_name']}: 반환 버킷 값 {', '.join(str(p['value']) for p in row['points'])}")
                else:
                    metrics.append(f"{row['metric_name']}: {row['data_status']}")
            line += "\n  " + " / ".join(metrics)
        lines.append(line + ".")
    lines.extend(["", "구성 상태만으로 애플리케이션 정상 여부를 판정하지 않았습니다."])
    return "\n".join(lines)


def _scope(evidence):
    queried = set()
    for result in evidence:
        called = {call["service"] for call in result["api_calls"] if call["service"] in SUPPORTED_SERVICES}
        if called:
            queried.update(called)
            if result["service"] in SUPPORTED_SERVICES:
                queried.add(result["service"])
    services = sorted(queried)
    omitted = sorted(set(SUPPORTED_SERVICES) - set(services))
    return ", ".join(services) or "없음", ", ".join(omitted) or "없음"


def _cell(value):
    return html.escape(str(value), quote=False).replace("|", "\\|").replace("\n", " ")


def render_markdown(record):
    evidence = record.get("evidence", [])
    queried, omitted = _scope(evidence)
    mode = "실제 조회" if record["mode"] == "live" else "샘플 데이터 · AWS 및 모델 호출 없음"
    accounts = ", ".join(sorted({str(r.get("account_id")) for r in evidence if r.get("account_id")}))
    lines = [
        "# AWS 운영 조회 보고서", "",
        f"- 모드: {mode}", f"- 계정 ID: {accounts or '확인되지 않음'}",
        "- 에이전트 실행·분석 리전: us-east-1",
        "- 조회 대상 리전: ap-northeast-2",
        f"- 작성 시각 UTC 원본: {record['created_at']}",
        f"- 작성 시각 Asia/Seoul 표시: {kst(record['created_at'])}",
        f"- 이번 조회 서비스: {queried}", f"- 지원 범위 중 미조회 서비스: {omitted}",
        f"- 요청: {_cell(record['prompt'])}", "",
        "## 서비스별 현황", "",
        "| 서비스 / 도구 | 결과 | 리소스 수 | 페이지 완료 | 잘림 |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for r in evidence:
        if r["service"] == "sts":
            continue
        lines.append(
            f"| {_cell(r['service'])} / {_cell(r['tool'])} | {STATUS_TEXT.get(r['status'], r['status'])} "
            f"| {r.get('resource_count', 0)} | {r['pagination_complete']} | {r['truncated']} |"
        )
    lines += ["", "## 관측 결과와 답변", "", html.escape(record.get("answer", ""), quote=False),
              "", "## 주의 항목", ""]
    notes = attention_items(evidence)
    lines.extend(f"- {_cell(note)}" for note in notes)
    if not notes:
        lines.append("별도 주의 항목이 추출되지 않았습니다. 이는 애플리케이션 정상 판정이 아닙니다.")
    if record.get("errors"):
        lines.append(f"- 실행 오류: {_cell(', '.join(record['errors']))}")
    lines += ["", "## 근거", ""]
    for i, result in enumerate(evidence, 1):
        apis = ", ".join(f"{c['service']}.{c['api']} [{c['region']}]" for c in result["api_calls"])
        lines += [
            f"### 근거 {i}: {_cell(result['tool'])}", "",
            f"- 관측 UTC 원본: {result['observed_at']}",
            f"- Asia/Seoul 표시: {kst(result['observed_at'])}",
            f"- API: {apis}",
            f"- 소요 시간: {result['duration_ms']} ms",
            "", "```json", json.dumps(result, ensure_ascii=False, indent=2), "```", "",
        ]
    lines += [
        "## 진단 가설과 추가 확인 사항", "",
        "- 위 API의 관측 사실만 근거로 삼습니다. 추가 근거가 없는 장애 원인 가설은 확정하지 않습니다.",
        "- EC2 running, RDS available, ECS ACTIVE 및 Lambda Active는 애플리케이션 정상 여부와 다릅니다.",
        "- 빈 결과·권한 거부·부분 결과·미조회 범위를 구분하고, 누락된 범위를 추가 확인합니다.",
        "- 지표 없음은 0이 아닙니다. UTC 조회 구간, 수집 주기, 지연 및 실제 호출 여부를 확인합니다.",
        "- DB SQL, 사설 HTTP, Kubernetes API, 로그 검색, 비용 분석은 이번 데모에서 실행하지 않았습니다.",
        "- 서울에서 조회한 정보 중 모델에 전달한 내용은 us-east-1 BMA 분석에 사용됩니다.",
    ]
    return "\n".join(lines) + "\n"


def render_html(record):
    def esc(value):
        return html.escape(str(value), quote=True)
    evidence = record.get("evidence", [])
    queried, omitted = _scope(evidence)
    mode = "실제 조회" if record["mode"] == "live" else "샘플 데이터 · AWS 및 모델 호출 없음"
    rows = "".join(
        f"<tr><td>{esc(r['service'])}</td><td>{esc(r['tool'])}</td>"
        f"<td>{esc(STATUS_TEXT.get(r['status'], r['status']))}</td><td>{r.get('resource_count', 0)}</td>"
        f"<td>{r['pagination_complete']}</td><td>{r['truncated']}</td></tr>"
        for r in evidence if r["service"] != "sts"
    )
    notes = "".join(f"<li>{esc(item)}</li>" for item in attention_items(evidence))
    details = "".join(
        f"<details><summary>{esc(r['tool'])} · {esc(r['observed_at'])} UTC / {esc(kst(r['observed_at']))}</summary>"
        f"<pre>{esc(json.dumps(r, ensure_ascii=False, indent=2))}</pre></details>" for r in evidence
    )
    return f"""<!doctype html>
<html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AWS 운영 조회 보고서</title>
<style>
body{{font:16px/1.7 system-ui,sans-serif;background:#f2f6fa;color:#193348;margin:0}}
main{{max-width:1100px;margin:auto;padding:40px 24px}}header{{border-bottom:3px solid #007c83}}
h1{{font-size:32px}}h2{{margin-top:36px}}table{{border-collapse:collapse;width:100%;background:white}}
td,th{{border:1px solid #d5e0e9;padding:10px;text-align:left}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;
background:white;padding:20px;border-radius:8px;font:14px/1.7 ui-monospace,monospace}}
.notice{{background:#e0eef2;padding:16px}}summary{{cursor:pointer;padding:12px}}details{{border-bottom:1px solid #ccdce6}}
</style><main><header><p>{esc(mode)}</p><h1>AWS 운영 조회 보고서</h1></header>
<p>요청: {esc(record['prompt'])}</p>
<p>작성 UTC 원본: {esc(record['created_at'])}<br>Asia/Seoul 표시: {esc(kst(record['created_at']))}</p>
<p>실행·분석 us-east-1 / 조회 ap-northeast-2<br>이번 조회: {esc(queried)} / 미조회: {esc(omitted)}</p>
<h2>서비스별 현황</h2><div style="overflow:auto"><table><thead><tr><th>서비스</th><th>도구</th><th>결과</th>
<th>리소스 수</th><th>페이지 완료</th><th>잘림</th></tr></thead><tbody>{rows}</tbody></table></div>
<h2>관측 결과와 답변</h2><pre>{esc(record.get('answer', ''))}</pre>
<h2>주의 항목</h2><ul>{notes or '<li>추출된 주의 항목 없음. 애플리케이션 정상 판정은 수행하지 않았습니다.</li>'}</ul>
<p>실행 오류: {esc(', '.join(record.get('errors', [])) or '없음')}</p>
<h2>근거</h2>{details}
<h2>진단 가설과 추가 확인 사항</h2>
<p>구성 상태는 애플리케이션 정상 여부의 증거가 아닙니다. 추가 근거 없는 원인 가설은 확정하지 않습니다.
지표 없음은 0이 아닙니다. 권한 부족과 부분 조회, 미조회 범위를 추가 확인하세요.</p>
<p>DB SQL, 사설 HTTP, Kubernetes API, 로그 검색 및 비용 분석은 이번 데모 범위에 포함하지 않았습니다.</p>
<p class="notice">서울 리소스 정보 중 모델에 전달한 내용은 us-east-1 BMA에서 분석됩니다.</p></main></html>"""
