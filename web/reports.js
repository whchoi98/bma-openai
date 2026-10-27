import { cleanMarkdownProse } from "./presentation.js";
import { prepareHtmlReport, reportHead } from "./report-rendering.js";
import { reportServiceScope } from "./history.js";

export const statusText = {
  ok: "조회 성공", empty: "조회 성공, 데이터 없음", partial: "일부 결과", access_denied: "접근 권한 없음",
  api_error: "API 호출 실패", account_mismatch: "계정 불일치로 차단", invalid_input: "입력 범위 오류",
  unsupported_service: "미지원 서비스",
};
const escape = (value) => String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
const cell = (value) => escape(value).replaceAll("|", "\\|").replaceAll("\n", " ");
function processingDescription(record) {
  if (record.mode === "sample") return "모델 호출 없음 (샘플 모드)";
  const scope = record.model_processing_scope || record.evidence?.find((r) => r.tool === "get_account_context")?.data?.[0]?.data_processing_scope;
  return scope === "global"
    ? "글로벌 Bedrock 추론 프로파일. 모델 처리 리전은 us-east-1에 고정되지 않음"
    : "BMA (us-east-1)";
}
export const koreanTime = (value) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "시각 확인 불가";
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Seoul", dateStyle: "short", timeStyle: "medium" }).format(date) + " KST";
};

export function attentionItems(evidence) {
  const notes = [];
  for (const result of evidence) {
    const prefix = `${result.service} / ${result.tool}`;
    if (!["ok", "empty"].includes(result.status)) notes.push(`${prefix}: ${statusText[result.status]} ${(result.errors || []).map((e) => e.code).join(", ")}`);
    if (result.truncated) notes.push(`${prefix}: 조회 한도로 결과가 잘렸습니다.`);
    if (result.missing_resource_ids?.length) notes.push(`${prefix}: 응답에 포함되지 않은 ID: ${result.missing_resource_ids.join(", ")}`);
    for (const row of result.data || []) {
      const id = row.id || row.resource_id || "";
      if (row.data_status === "no_data") notes.push(`${id} / ${row.metric_name}: 데이터 없음. 실제 호출 여부, 수집 주기와 지연을 추가 확인합니다.`);
      if (["instance_status", "system_status", "attached_ebs_status"].some((key) => row[key] === "impaired")) notes.push(`${id}: EC2 상태 점검 impaired 관측. 애플리케이션 영향은 별도 확인이 필요합니다.`);
      if (Number.isInteger(row.running_count) && row.running_count < row.desired_count) notes.push(`${id}: 실행 태스크 ${row.running_count}개 / 목표 ${row.desired_count}개. 배포 상태와 영향을 추가 확인합니다.`);
      if (row.state === "ALARM") notes.push(`${id}: CloudWatch ALARM 상태 관측.`);
      if (["Errors", "Throttles"].includes(row.metric_name) && row.points?.length) {
        const total = row.points.reduce((sum, point) => sum + point.value, 0);
        if (total > 0) notes.push(`${id} / ${row.metric_name}: 반환된 버킷의 관측 합계 ${total}. 수집 구간과 결측 여부를 함께 확인합니다.`);
      }
    }
  }
  return [...new Set(notes)];
}

export function summarize(evidence, language = "ko") {
  if (language === "en") return summarizeEnglish(evidence);
  return evidence.filter((r) => r.service !== "sts").map((result) => {
    const states = {};
    for (const row of result.data) if (row.state) states[row.state] = (states[row.state] || 0) + 1;
    let text = `- ${result.service} / ${result.tool}: ${statusText[result.status]}, 응답에 포함된 리소스 ${result.resource_count}개`;
    if (Object.keys(states).length) text += ` (${Object.entries(states).map(([state, n]) => `${state} ${n}개`).join(", ")})`;
    if ("datapoint_count" in result) text += `, 데이터 포인트 ${result.datapoint_count}개`;
    if ("datapoint_count" in result) text += "\n  " + result.data.map((row) => {
      if (row.data_status === "no_data") return `${row.metric_name}: 데이터 없음`;
      if (!row.points?.length) return `${row.metric_name}: ${row.data_status}`;
      return row.statistic === "Sum"
        ? `${row.metric_name}: 반환된 버킷의 합계 ${row.points.reduce((sum, p) => sum + p.value, 0)}`
        : `${row.metric_name}: 반환 버킷 값 ${row.points.map((p) => p.value).join(", ")}`;
    }).join(" / ");
    return text + ".";
  }).join("\n") + "\n\n구성 상태만으로 애플리케이션 정상 여부를 판정하지 않았습니다.";
}

export function renderMarkdown(record) {
  if (record.language === "en") return renderEnglish(record, "md");
  const evidence = record.evidence || [];
  const { queried_services: queried, unqueried_services: omitted } = reportServiceScope(record);
  const lines = [
    "# AWS 운영 조회 보고서", "",
    `- 모드: ${record.mode === "live" ? "실제 조회" : "샘플 데이터, AWS 및 모델 호출 없음"}`,
    `- 계정 ID: ${[...new Set(evidence.map((r) => r.account_id).filter(Boolean))].join(", ") || "확인되지 않음"}`,
    "- 앱과 Runtime 실행 리전: us-east-1", "- 조회 대상 리전: ap-northeast-2",
    `- 모델 처리 경로: ${processingDescription(record)}`,
    ...(record.model ? [`- 모델: ${cell(record.model)}`] : []),
    `- 작성 시각 UTC 원본: ${record.created_at}`, `- 작성 시각 Asia/Seoul 표시: ${koreanTime(record.created_at)}`,
    `- 이번 조회 서비스: ${queried.join(", ") || "없음"}`, `- 지원 범위 중 미조회 서비스: ${omitted.join(", ") || "없음"}`,
    `- 요청: ${cell(record.prompt)}`, "", "## 서비스별 현황", "",
    "| 서비스 / 도구 | 결과 | 리소스 수 | 페이지 완료 | 잘림 |", "| --- | --- | ---: | --- | --- |",
  ];
  for (const r of evidence.filter((r) => r.service !== "sts")) lines.push(`| ${cell(r.service)} / ${cell(r.tool)} | ${statusText[r.status]} | ${r.resource_count} | ${r.pagination_complete} | ${r.truncated} |`);
  lines.push("", "## 관측 결과와 답변", "", escape(cleanMarkdownProse(record.answer || "")), "", "## 주의 항목", "");
  const notes = attentionItems(evidence);
  lines.push(...(notes.length ? notes.map((note) => "- " + cell(note)) : ["추출된 주의 항목 없음. 애플리케이션 정상 판정은 수행하지 않았습니다."]));
  if (record.errors?.length) lines.push(`- 실행 오류: ${cell(record.errors.join(", "))}`);
  lines.push("", "## 근거", "");
  for (const r of evidence) {
    lines.push(`### ${cell(r.tool)}`, "", `- 관측 UTC 원본: ${r.observed_at}`, `- Asia/Seoul 표시: ${koreanTime(r.observed_at)}`,
      `- API: ${r.api_calls.map((c) => `${c.service}.${c.api} [${c.region}]`).join(", ")}`,
      `- 소요 시간: ${r.duration_ms} ms`, "", "```json", JSON.stringify(r, null, 2), "```", "");
  }
  lines.push("## 진단 가설과 추가 확인 사항", "",
    "- 추가 근거 없는 장애 원인 가설은 확정하지 않습니다. 구성 상태와 애플리케이션 정상 여부를 구분합니다.",
    "- 지표 없음은 0이 아닙니다. 빈 목록, 권한 거부, 부분 결과, 미조회 범위를 구분합니다.",
    "- DB SQL, 사설 HTTP, Kubernetes API, 로그 검색 및 비용 분석은 이번 데모 범위에서 제외했습니다.",
    `- 서울 리소스 정보 중 모델에 전달한 내용의 처리 경로: ${processingDescription(record)}.`);
  return lines.join("\n") + "\n";
}

export function renderHtml(record, options = {}) {
  const prepared = prepareHtmlReport(record, options);
  record = prepared.record;
  const answerHtml = prepared.answerHtml;
  if (record.language === "en") return renderEnglish(record, "html", { ...options, answerHtml });
  const evidence = record.evidence || [];
  const { queried_services: queried, unqueried_services: omitted } = reportServiceScope(record);
  const rows = evidence.filter((r) => r.service !== "sts").map((r) => `<tr><td>${escape(r.service)}</td><td>${escape(r.tool)}</td><td>${escape(statusText[r.status])}</td><td>${r.resource_count}</td><td>${r.pagination_complete}</td><td>${r.truncated}</td></tr>`).join("");
  const notes = attentionItems(evidence).map((note) => `<li>${escape(note)}</li>`).join("");
  const details = evidence.map((r) => `<details><summary>${escape(r.tool)}: ${escape(r.observed_at)} UTC / ${escape(koreanTime(r.observed_at))}</summary><pre>${escape(JSON.stringify(r, null, 2))}</pre></details>`).join("");
  return `${reportHead("ko", options)}
<main><header><p>${record.mode === "live" ? "실제 조회" : "샘플 데이터, AWS 및 모델 호출 없음"}</p><h1>AWS 운영 조회 보고서</h1></header>
<p>요청: ${escape(record.prompt)}</p><p>UTC 원본: ${escape(record.created_at)}<br>Asia/Seoul 표시: ${escape(koreanTime(record.created_at))}</p>
<p>앱과 Runtime 실행 us-east-1 / 조회 ap-northeast-2<br>모델 처리: ${escape(processingDescription(record))}${record.model ? "<br>모델: " + escape(record.model) : ""}<br>이번 조회: ${escape(queried.join(", ") || "없음")} / 미조회: ${escape(omitted.join(", ") || "없음")}</p>
<h2>서비스별 현황</h2><div class="report-table"><table><thead><tr><th>서비스</th><th>도구</th><th>결과</th><th>리소스 수</th><th>페이지 완료</th><th>잘림</th></tr></thead><tbody>${rows}</tbody></table></div>
<h2>관측 결과와 답변</h2><section id="report-answer">${answerHtml}</section><h2>주의 항목</h2><ul>${notes || "<li>추출된 주의 항목 없음. 애플리케이션 정상 판정은 수행하지 않았습니다.</li>"}</ul>
<p>실행 오류: ${escape(record.errors?.join(", ") || "없음")}</p><h2>근거</h2>${details}<h2>진단 가설과 추가 확인 사항</h2>
<p>구성 상태는 애플리케이션 정상의 증거가 아닙니다. 지표 없음은 0이 아닙니다. 추가 근거 없는 원인 가설을 확정하지 않습니다. 권한 부족, 부분 조회, 미조회 범위를 추가 확인하세요.</p>
<p>DB SQL, 사설 HTTP, Kubernetes API, 로그 검색 및 비용 분석은 제외했습니다.</p>
<p>서울 정보 중 모델에 전달한 내용의 처리 경로: ${escape(processingDescription(record))}.</p></main></body></html>`;
}


const englishStatus = {
  ok: "Success", empty: "No data", partial: "Partial results", access_denied: "Access denied",
  api_error: "API failure", account_mismatch: "Blocked: account mismatch", invalid_input: "Invalid input",
  unsupported_service: "Unsupported service",
};

function summarizeEnglish(evidence) {
  return evidence.filter((r) => r.service !== "sts").map((r) => {
    let line = `- ${r.service} / ${r.tool}: ${englishStatus[r.status]}, ${r.resource_count} resources returned`;
    if ("datapoint_count" in r) {
      line += `, ${r.datapoint_count} data points. ` + r.data.map((row) => {
        if (row.data_status === "no_data") return `${row.metric_name}: no data`;
        if (!row.points?.length) return `${row.metric_name}: ${row.data_status}`;
        return row.statistic === "Sum"
          ? `${row.metric_name}: sum of returned buckets ${row.points.reduce((sum, p) => sum + p.value, 0)}`
          : `${row.metric_name}: returned bucket values ${row.points.map((p) => p.value).join(", ")}`;
      }).join("; ");
    }
    return line + ".";
  }).join("\n") + "\n\nConfiguration states do not establish application health.";
}

function englishNotes(evidence) {
  const notes = [];
  for (const r of evidence) {
    if (!["ok", "empty"].includes(r.status)) notes.push(`${r.tool}: ${englishStatus[r.status]}. ${(r.errors || []).map((e) => e.code).join(", ")}`);
    if (r.truncated) notes.push(`${r.tool}: results were truncated at the query limit.`);
    if (r.missing_resource_ids?.length) notes.push(`${r.tool}: missing IDs: ${r.missing_resource_ids.join(", ")}`);
    for (const row of r.data || []) {
      const id = row.id || row.resource_id || "";
      if (row.data_status === "no_data") notes.push(`${id} / ${row.metric_name}: no data. This does not mean zero or healthy.`);
      if (["instance_status", "system_status", "attached_ebs_status"].some((key) => row[key] === "impaired")) notes.push(`${id}: impaired EC2 status check observed. Application impact has not been established.`);
      if (Number.isInteger(row.running_count) && row.running_count < row.desired_count) notes.push(`${id}: ${row.running_count} running tasks, ${row.desired_count} desired. Check deployment state and impact.`);
      if (row.state === "ALARM") notes.push(`${id}: CloudWatch ALARM observed.`);
      if (["Errors", "Throttles"].includes(row.metric_name) && row.points?.length) {
        const total = row.points.reduce((sum, p) => sum + p.value, 0);
        if (total > 0) notes.push(`${id} / ${row.metric_name}: returned bucket sum ${total}. Check the observation window and missing data.`);
      }
    }
  }
  return [...new Set(notes)];
}

function renderEnglish(record, format, options = {}) {
  const evidence = record.evidence || [];
  const { queried_services: queried, unqueried_services: omitted } = reportServiceScope(record);
  const rows = evidence.filter((r) => r.service !== "sts");
  const accounts = [...new Set(evidence.map((r) => r.account_id).filter(Boolean))].join(", ") || "Not verified";
  const scope = record.model_processing_scope || evidence.find((r) => r.tool === "get_account_context")?.data?.[0]?.data_processing_scope;
  const processing = record.mode === "sample" ? "No model calls (sample mode)."
    : scope === "global" ? "Global Bedrock inference profile. Processing is not restricted to us-east-1." : "BMA in us-east-1 (N. Virginia).";
  const notes = englishNotes(evidence);
  const facts = [
    ["Mode", record.mode === "live" ? "Live AWS queries" : "Sample data, no AWS or model calls"],
    ["Account ID", accounts], ["App and Runtime Region", "us-east-1"], ["Query Region", "ap-northeast-2"],
    ["Model processing", processing], ["Model", record.model || "No model calls"],
    ["Created at (UTC original)", record.created_at], ["Created at (Asia/Seoul display)", koreanTime(record.created_at)],
    ["Queried services", queried.join(", ") || "None"], ["Supported services not queried", omitted.join(", ") || "None"],
    ["Request", record.prompt],
  ];
  const followup = "Configuration states do not establish application health. Missing metrics are not zero. Distinguish empty, denied, partial, and unqueried results. SQL, private HTTP, Kubernetes API, log search, and cost analysis are outside this demo.";
  if (format === "md") {
    const lines = ["# AWS operations report", "", ...facts.map(([key, value]) => `- ${key}: ${cell(value)}`), "", "## Service inventory", "",
      "| Service / tool | Result | Resources | Pagination complete | Truncated |", "| --- | --- | ---: | --- | --- |",
      ...rows.map((r) => `| ${cell(r.service)} / ${cell(r.tool)} | ${englishStatus[r.status]} | ${r.resource_count} | ${r.pagination_complete} | ${r.truncated} |`),
      "", "## Observations and answer", "", escape(cleanMarkdownProse(record.answer || "")), "", "## Items to check", "",
      ...(notes.length ? notes.map((note) => `- ${cell(note)}`) : ["No specific findings extracted. Application health has not been established."]),
      `- Execution errors: ${cell(record.errors?.join(", ") || "None")}`, "", "## Evidence", ""];
    for (const r of evidence) lines.push(`### ${cell(r.tool)}`, "", `- Observed at (UTC original): ${r.observed_at}`,
      `- Asia/Seoul display: ${koreanTime(r.observed_at)}`, `- APIs: ${r.api_calls.map((c) => `${c.service}.${c.api} [${c.region}]`).join(", ")}`,
      `- Duration: ${r.duration_ms} ms`, "", "```json", JSON.stringify(r, null, 2), "```", "");
    lines.push("## Limits and follow-up", "", followup);
    return lines.join("\n") + "\n";
  }
  const table = rows.map((r) => `<tr><td>${escape(r.service)}</td><td>${escape(r.tool)}</td><td>${englishStatus[r.status]}</td><td>${r.resource_count}</td><td>${r.pagination_complete}</td><td>${r.truncated}</td></tr>`).join("");
  const details = evidence.map((r) => `<details><summary>${escape(r.tool)}: ${escape(r.observed_at)} UTC / ${escape(koreanTime(r.observed_at))}</summary><pre>${escape(JSON.stringify(r, null, 2))}</pre></details>`).join("");
  return `${reportHead("en", options)}
<main><h1>AWS operations report</h1><dl>${facts.map(([key, value]) => `<dt>${key}</dt><dd>${escape(value)}</dd>`).join("")}</dl>
<h2>Service inventory</h2><div class="report-table"><table><thead><tr><th>Service</th><th>Tool</th><th>Result</th><th>Resources</th><th>Pagination complete</th><th>Truncated</th></tr></thead><tbody>${table}</tbody></table></div>
<h2>Observations and answer</h2><section id="report-answer">${options.answerHtml}</section><h2>Items to check</h2><ul>${notes.length ? notes.map((note) => `<li>${escape(note)}</li>`).join("") : "<li>No specific findings extracted. Application health has not been established.</li>"}</ul>
<p>Execution errors: ${escape(record.errors?.join(", ") || "None")}</p><h2>Evidence</h2>${details}<h2>Limits and follow-up</h2><p>${followup}</p></main></body></html>`;
}
