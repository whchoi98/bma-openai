import { createElement } from "react";
import { createRoot } from "react-dom/client";
import { MarkdownResult } from "./markdown.js";
import { cleanNarrative, displayAccountId, displayModel, maskAccountIds } from "../presentation.js";
import { applyLanguage, translate } from "./i18n.js";
import { ResourceInsights } from "./resource-insights.js";
import { createHistoryPanel } from "./history-panel.js";
import { createInvestigationPanel } from "./investigations.js";

const byId = (id) => document.getElementById(id);
function preference(key, fallback) {
  try { return localStorage.getItem(key) || fallback; } catch { return fallback; }
}
function savePreference(key, value) {
  try { localStorage.setItem(key, value); } catch { /* Display preferences are optional. */ }
}
let language = preference("aws-desk-language", "ko") === "en" ? "en" : "ko";
let theme = preference("aws-desk-theme", matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
const t = (key, values) => translate(language, key, values);
let currentRun = null;
let currentContext = null;
let shownAccount = "";
let accountSource = "accountPending";
let lastObservedAt = null;
let lastErrorCode = null;
let interrupted = false;
let displayedEvidence = [];
let elapsedSeconds = 0;
let traceCount = 0;
let connected = false;
let busy = false;
const answerRoot = createRoot(byId("answer"));
let streamedAnswer = "";
let renderFrame = null;
let elapsedTimer = null;
let queryStartedAt = 0;
const accounts = new Set();
let previewRequest = null;
let historyPanel = null;
let showingSaved = false;
let investigationPanel = null;
let workspaceMode = "question";
let singleQuestionView = null;
const insightsRoot = createRoot(byId("resource-insights"));

function renderAnswer(markdown, streaming = false, incomplete = false) {
  byId("answer").className = "answer";
  byId("answer").setAttribute("aria-busy", String(streaming));
  answerRoot.render(createElement(MarkdownResult, { markdown, streaming, incomplete, accounts: [...accounts], language }));
}

function renderInsights() {
  insightsRoot.render(createElement(ResourceInsights, { evidence: displayedEvidence, language, accounts: [...accounts] }));
}

function setPhase(message) {
  byId("phase").textContent = cleanNarrative(maskAccountIds(message, accounts));
}

function updateElapsed() {
  elapsedSeconds = Math.floor((performance.now() - queryStartedAt) / 1000);
  byId("elapsed").textContent = t("seconds", { n: elapsedSeconds });
}

function stopProgress() {
  if (renderFrame !== null) cancelAnimationFrame(renderFrame);
  renderFrame = null;
  if (elapsedTimer !== null) clearInterval(elapsedTimer);
  elapsedTimer = null;
  byId("stream-meta").classList.remove("active");
  byId("answer").setAttribute("aria-busy", "false");
}

function appendAnswer(delta) {
  if (typeof delta !== "string") return;
  streamedAnswer += delta;
  if (streamedAnswer.length > 60_000) throw new Error("ResponseTooLarge");
  setPhase(t("writing"));
  byId("run-status").textContent = t("writing");
  if (renderFrame === null) {
    renderFrame = requestAnimationFrame(() => {
      renderFrame = null;
      renderAnswer(streamedAnswer, true);
    });
  }
}

function headers() {
  const key = byId("access-key").value;
  return key ? { Authorization: `Bearer ${key}` } : {};
}

function explain(error) {
  const message = t(error);
  return message === error ? t("unknownError", { code: error }) : message;
}

async function checked(response) {
  if (response.ok) return response;
  const body = await response.json().catch(() => ({}));
  throw new Error(typeof body.detail === "string" ? body.detail : (body.error || `HTTP${response.status}`));
}

function setBusy(value) {
  busy = value;
  byId("submit").disabled = value || !connected;
  byId("connect").disabled = value;
  byId("language-toggle").disabled = value;
  historyPanel?.setDisabled(value || !connected);
  investigationPanel?.setDisabled(value || !connected);
  byId("mode-question").disabled = value;
  byId("mode-investigation").disabled = value;
  document.querySelectorAll("[data-prompt-key]").forEach((button) => { button.disabled = value || !connected; });
}

function showTime(iso) {
  lastObservedAt = iso;
  const date = new Date(iso);
  const local = Number.isNaN(date.getTime()) ? t("checkRequired") : new Intl.DateTimeFormat(language === "en" ? "en-GB" : "ko-KR", {
    dateStyle: "short", timeStyle: "medium", timeZone: "Asia/Seoul", hour12: false,
  }).format(date);
  byId("observation-time").replaceChildren();
  for (const text of [`UTC ${iso}`, `Asia/Seoul ${local}`]) {
    const line = document.createElement("span");
    line.textContent = text;
    byId("observation-time").append(line);
  }
}

function renderContext() {
  byId("account").textContent = shownAccount ? displayAccountId(shownAccount) : t("checkRequired");
  byId("account-source").textContent = t(accountSource);
  if (!currentContext) {
    byId("mode").textContent = t("modePending");
    byId("mode").className = "pill";
    byId("model-label").textContent = t("modelPending");
    byId("model-id").textContent = "";
    byId("data-flow").textContent = t("flowPending");
    return;
  }
  const sample = currentContext.mode === "sample";
  byId("mode").textContent = t(sample ? "sample" : "live");
  byId("mode").className = `pill ${currentContext.mode}`;
  byId("model-label").textContent = currentContext.model ? `${t("model")}: ${displayModel(currentContext.model)}` : t("noModel");
  byId("model-id").textContent = currentContext.model || "";
  byId("data-flow").textContent = t(sample ? "flowSample" : currentContext.model_processing_scope === "global" ? "flowGlobal" : "flowBma");
}

function applyTheme() {
  theme = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = theme;
  byId("theme-toggle").textContent = t(theme === "dark" ? "lightMode" : "darkMode");
  byId("theme-toggle").setAttribute("aria-pressed", String(theme === "dark"));
}

function completedState() {
  if (!currentRun) return;
  setPhase(t(showingSaved ? "historyLoaded" : currentRun.status === "complete" ? "done" : "scopeReminder"));
  byId("run-status").textContent = workspaceMode === "investigation" ? t(`investigationStatus_${currentRun.status}`)
    : t({ complete: "done", partial: "partial", failed: "failed" }[currentRun.status] || "failed");
  byId("notice").textContent = [...(currentRun.errors || []), ...(lastErrorCode ? [lastErrorCode] : [])].map(explain).join(" ");
}

function refreshLanguage() {
  applyLanguage(language);
  byId("report-preview-frame").title = t("htmlReport");
  byId("language-toggle").textContent = language === "ko" ? "English" : "한국어";
  byId("language-toggle").setAttribute("aria-label", language === "ko" ? "Switch to English" : "한국어로 전환");
  document.querySelector(".top-menu").setAttribute("aria-label", t("toolbar"));
  applyTheme();
  renderContext();
  renderInsights();
  historyPanel?.render();
  investigationPanel?.render();
  byId("trace-count").textContent = t("queries", { n: traceCount });
  if (lastObservedAt) showTime(lastObservedAt);
  else byId("observation-time").textContent = t("notQueried");
  if (queryStartedAt) byId("elapsed").textContent = t("seconds", { n: elapsedSeconds });
  if (displayedEvidence.length) {
    traceCount = 0;
    byId("trace-body").replaceChildren();
    byId("evidence-details").replaceChildren();
    for (const result of displayedEvidence) addTrace(result, false);
  }
  if (workspaceMode === "investigation") {
    const state = investigationPanel?.getState();
    if (state?.run) renderInvestigationSnapshot({ investigation: state.investigation, run: state.run });
    else clearInvestigationView();
    return;
  }
  if (currentRun) {
    completedState();
  } else if (interrupted) {
    renderAnswer(streamedAnswer || t("failed"), false, true);
    byId("run-status").textContent = t("failed");
    byId("run-status").className = "status failed";
    setPhase(t("disconnected"));
    byId("notice").textContent = lastErrorCode ? explain(lastErrorCode) : "";
  } else {
    byId("run-status").textContent = t("idle");
    setPhase(t("questionPending"));
    renderAnswer(t("emptyAnswer"));
    byId("notice").textContent = lastErrorCode ? explain(lastErrorCode) : "";
  }
}

async function connect() {
  try {
    const response = await checked(await fetch("/api/context", { headers: headers(), cache: "no-store" }));
    const context = await response.json();
    currentContext = context;
    lastErrorCode = null;
    connected = true;
    accounts.add(context.account_id);
    shownAccount = context.account_id;
    accountSource = context.mode === "sample" ? "sampleAccount" : "accountConnected";
    renderContext();
    byId("notice").textContent = "";
  } catch (error) {
    connected = false;
    currentContext = null;
    shownAccount = "";
    accountSource = "accountRequired";
    renderContext();
    lastErrorCode = error.message;
    byId("notice").textContent = explain(error.message);
  }
  setBusy(busy);
  if (connected) {
    historyPanel?.refresh(true);
    investigationPanel?.connect();
  } else investigationPanel?.disconnect();
}

function replaceEvidence(evidence) {
  displayedEvidence = [...(evidence || [])];
  traceCount = 0;
  lastObservedAt = null;
  byId("trace-body").replaceChildren();
  byId("evidence-details").replaceChildren();
  byId("trace-count").textContent = t("zeroQueries");
  byId("observation-time").textContent = t("notQueried");
  for (const result of displayedEvidence) addTrace(result, false);
  renderInsights();
}

function setReportAvailability(available) {
  for (const id of ["download-md", "download-html", "preview-html", "download-docx", "download-pptx"]) {
    byId(id).disabled = !available;
  }
}

function clearInvestigationView() {
  closeReportPreview();
  stopProgress();
  currentRun = null;
  streamedAnswer = "";
  lastErrorCode = null;
  interrupted = false;
  queryStartedAt = 0;
  byId("elapsed").textContent = "";
  byId("notice").textContent = "";
  byId("run-status").textContent = t("idle");
  byId("run-status").className = "status idle";
  byId("investigation-selected-prompt").hidden = true;
  replaceEvidence([]);
  setReportAvailability(false);
  renderAnswer(t("investigationWaiting"));
  setPhase(t("investigationWaiting"));
}

function renderInvestigationSnapshot({ run }) {
  if (workspaceMode !== "investigation") return;
  if (currentRun?.id !== run.id) closeReportPreview();
  stopProgress();
  queryStartedAt = 0;
  byId("elapsed").textContent = "";
  lastErrorCode = null;
  interrupted = false;
  showingSaved = true;
  currentRun = null;
  streamedAnswer = run.answer || "";
  replaceEvidence(run.evidence);
  const active = ["queued", "running"].includes(run.status);
  const phaseKey = `investigationPhase_${run.phase}`;
  const phase = t(phaseKey) !== phaseKey ? t(phaseKey) : t(`investigationStatus_${run.status}`);
  renderAnswer(streamedAnswer || phase, active, !active && Boolean(run.errors?.length));
  byId("run-status").className = `status ${active ? "working" : run.status}`;
  byId("run-status").textContent = t(`investigationStatus_${run.status}`);
  byId("stream-meta").classList.toggle("active", active && investigationPanel?.getState().connection === "streaming");
  setPhase(phase);
  byId("notice").textContent = (run.errors || []).map(explain).join(" ");
  byId("investigation-selected-prompt").textContent = cleanNarrative(maskAccountIds(run.prompt || "", accounts, { strict: true }));
  byId("investigation-selected-prompt").hidden = false;
  setReportAvailability(false);
  if (run.result) renderInvestigationResult(run.result);
}

function renderInvestigationResult(record) {
  if (workspaceMode !== "investigation") return;
  replaceEvidence(record.evidence);
  handle({ ...record, type: "complete" });
}

function switchWorkspace(mode) {
  if (busy || workspaceMode === mode) return;
  closeReportPreview();
  if (workspaceMode === "question") {
    singleQuestionView = { currentRun, streamedAnswer, displayedEvidence: [...displayedEvidence], lastErrorCode,
      interrupted, showingSaved, elapsedSeconds, queryStartedAt };
  }
  workspaceMode = mode;
  byId("single-question-workspace").hidden = mode !== "question";
  byId("investigation-workspace").hidden = mode !== "investigation";
  byId("mode-question").setAttribute("aria-pressed", String(mode === "question"));
  byId("mode-investigation").setAttribute("aria-pressed", String(mode === "investigation"));
  if (mode === "investigation") {
    const state = investigationPanel.getState();
    if (state.run) renderInvestigationSnapshot({ investigation: state.investigation, run: state.run });
    else clearInvestigationView();
    investigationPanel.render();
    return;
  }
  stopProgress();
  byId("investigation-selected-prompt").hidden = true;
  const saved = singleQuestionView;
  currentRun = saved?.currentRun || null;
  streamedAnswer = saved?.streamedAnswer || "";
  lastErrorCode = saved?.lastErrorCode || null;
  interrupted = saved?.interrupted || false;
  showingSaved = saved?.showingSaved || false;
  elapsedSeconds = saved?.elapsedSeconds || 0;
  queryStartedAt = saved?.queryStartedAt || 0;
  replaceEvidence(saved?.displayedEvidence || []);
  setReportAvailability(currentRun?.report_available);
  byId("elapsed").textContent = queryStartedAt ? t("seconds", { n: elapsedSeconds }) : "";
  if (currentRun) {
    renderAnswer(currentRun.answer, false, Boolean(currentRun.errors?.length));
    byId("run-status").className = `status ${currentRun.status}`;
  } else byId("run-status").className = `status ${interrupted ? "failed" : "idle"}`;
  refreshLanguage();
}

function reset() {
  closeReportPreview();
  stopProgress();
  streamedAnswer = "";
  currentRun = null;
  lastErrorCode = null;
  interrupted = false;
  showingSaved = false;
  displayedEvidence = [];
  renderInsights();
  traceCount = 0;
  byId("trace-body").replaceChildren();
  byId("evidence-details").replaceChildren();
  byId("trace-count").textContent = t("zeroQueries");
  renderAnswer(t("starting"));
  byId("notice").textContent = "";
  byId("download-md").disabled = true;
  byId("download-html").disabled = true;
  byId("preview-html").disabled = true;
  byId("download-docx").disabled = true;
  byId("download-pptx").disabled = true;
  byId("run-status").className = "status working";
  byId("run-status").textContent = t("querying");
  queryStartedAt = performance.now();
  updateElapsed();
  elapsedTimer = setInterval(updateElapsed, 1000);
  byId("stream-meta").classList.add("active");
  setPhase(t("preparing"));
}

function addTrace(result, record = true) {
  if (record) displayedEvidence.push(result);
  if (!streamedAnswer) setPhase(t("querying"));
  if (result.account_id) accounts.add(result.account_id);
  traceCount += 1;
  byId("trace-count").textContent = t("queries", { n: traceCount });
  const row = document.createElement("tr");
  const tool = document.createElement("td");
  tool.textContent = result.tool;
  const region = document.createElement("small");
  region.textContent = result.region;
  tool.append(region);
  const duration = document.createElement("td");
  duration.textContent = `${Number(result.duration_ms).toLocaleString(language === "en" ? "en-US" : "ko-KR", { maximumFractionDigits: 1 })} ms`;
  const count = document.createElement("td");
  count.textContent = "datapoint_count" in result ? t("points", { n: result.datapoint_count }) : t("records", { n: result.count });
  const status = document.createElement("td");
  status.textContent = t(result.status);
  status.className = ["ok", "empty"].includes(result.status) ? "result-label" : "error-state";
  row.append(tool, duration, count, status);
  byId("trace-body").append(row);
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  const apis = result.api_calls.map((call) => `${call.service}.${call.api}`).join(", ");
  summary.textContent = `${result.tool}: ${apis}`;
  const content = document.createElement("pre");
  content.textContent = maskAccountIds(JSON.stringify(result, null, 2), accounts, { strict: true });
  details.append(summary, content);
  byId("evidence-details").append(details);
  showTime(result.observed_at);
  if (result.api_calls.some((call) => call.api === "GetCallerIdentity" && call.success === false)) {
    shownAccount = "";
    accountSource = "accountFailure";
    byId("account").textContent = t("checkFailed");
  } else if (result.account_id) {
    shownAccount = result.account_id;
    byId("account").textContent = displayAccountId(shownAccount);
    accountSource = result.mode === "sample" ? "sampleAccount"
      : result.status === "account_mismatch" ? "accountMismatch" : "accountVerified";
  }
  byId("account-source").textContent = t(accountSource);
  renderInsights();
}

function handle(event) {
  if (event.type === "tool_result") addTrace(event.result);
  if (event.type === "progress") {
    setPhase(event.message);
    if (!streamedAnswer) renderAnswer(event.message);
  }
  if (event.type === "answer_delta") appendAnswer(event.delta);
  if (event.type === "error") throw new Error(event.code);
  if (event.type === "complete") {
    currentRun = event;
    lastErrorCode = null;
    interrupted = false;
    displayedEvidence = [...(event.evidence || [])];
    for (const result of event.evidence || []) if (result.account_id) accounts.add(result.account_id);
    stopProgress();
    renderAnswer(event.answer, false, Boolean(event.errors?.length));
    byId("run-status").className = `status ${event.status}`;
    completedState();
    byId("download-md").disabled = !event.report_available;
    byId("download-html").disabled = !event.report_available;
    byId("preview-html").disabled = !event.report_available;
    byId("download-docx").disabled = !event.report_available;
    byId("download-pptx").disabled = !event.report_available;
    renderInsights();
    historyPanel?.render();
  }
}

async function query(event) {
  event.preventDefault();
  if (busy || !connected || workspaceMode !== "question") return;
  const prompt = byId("prompt").value.trim();
  if (!prompt) return;
  reset();
  setBusy(true);
  try {
    const response = await checked(await fetch("/api/chat", {
      method: "POST", headers: { ...headers(), "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, language }),
    }));
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        if (buffer.length > 4_000_000) throw new Error("ResponseTooLarge");
        let boundary;
        while ((boundary = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const data = frame.split("\n").filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trim()).join("\n");
          if (data) handle(JSON.parse(data));
        }
        if (done) break;
      }
      if (!currentRun) throw new Error("EventStreamDisconnected");
    } finally {
      await reader.cancel().catch(() => {});
    }
  } catch (error) {
    lastErrorCode = error.message;
    interrupted = true;
    stopProgress();
    if (streamedAnswer) renderAnswer(streamedAnswer, false, true);
    setPhase(t("disconnected"));
    byId("notice").textContent = explain(error.message);
    byId("run-status").textContent = t("failed");
    byId("run-status").className = "status failed";
  } finally {
    setBusy(false);
    if (currentRun && !showingSaved) historyPanel?.refresh(true);
  }
}

async function loadSavedRun(id) {
  if (busy || !connected) return;
  setBusy(true);
  try {
    const response = await checked(await fetch(`/api/runs/${encodeURIComponent(id)}`, { headers: headers() }));
    const record = await response.json();
    if (record.id !== id || !Array.isArray(record.evidence)) throw new Error("ReportReadFailed");
    reset();
    showingSaved = true;
    if (record.account_id) accounts.add(record.account_id);
    for (const result of record.evidence) addTrace(result);
    byId("prompt").value = maskAccountIds(record.prompt || "", accounts, { strict: true });
    handle({ ...record, type: "complete" });
    queryStartedAt = 0;
    byId("elapsed").textContent = "";
    completedState();
  } catch (error) {
    lastErrorCode = error.message;
    byId("notice").textContent = explain(error.message);
  } finally { setBusy(false); }
}

async function download(format) {
  const run = currentRun;
  if (!run) return;
  const accountIds = [...accounts];
  const appearance = theme;
  try {
    const query = format === "html" ? `?view=download&theme=${appearance}` : "";
    const response = await checked(await fetch(`/api/runs/${encodeURIComponent(run.id)}/report.${format}${query}`, { headers: headers() }));
    const binary = ["docx", "pptx"].includes(format);
    const content = binary ? await response.arrayBuffer()
      : maskAccountIds(await response.text(), accountIds, { partial: Boolean(run.errors?.length), strict: true });
    const url = URL.createObjectURL(new Blob([content], {
      type: response.headers.get("content-type") || "application/octet-stream",
    }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `aws-report-${run.id}.${format}`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    if (currentRun?.id !== run.id) return;
    lastErrorCode = error.message;
    byId("notice").textContent = explain(error.message);
    if (byId("report-preview").open) {
      byId("report-preview-status").hidden = false;
      byId("report-preview-status").textContent = explain(error.message);
    }
  }
}

function clearReportPreview() {
  previewRequest?.abort();
  previewRequest = null;
  const frame = byId("report-preview-frame");
  frame.onload = null;
  frame.removeAttribute("srcdoc");
  frame.hidden = true;
  byId("preview-download").disabled = true;
  byId("report-preview").removeAttribute("aria-busy");
}

function closeReportPreview() {
  if (byId("report-preview").open) byId("report-preview").close();
  clearReportPreview();
}

async function openReportPreview() {
  if (!currentRun?.report_available || byId("report-preview").open) return;
  const dialog = byId("report-preview");
  const status = byId("report-preview-status");
  const frame = byId("report-preview-frame");
  const controller = new AbortController();
  previewRequest = controller;
  status.textContent = t("loadingReport");
  status.hidden = false;
  dialog.setAttribute("aria-busy", "true");
  dialog.showModal();
  try {
    const response = await checked(await fetch(
      `/api/runs/${encodeURIComponent(currentRun.id)}/report.html?view=preview&theme=${theme}`,
      { headers: headers(), signal: AbortSignal.any([controller.signal, AbortSignal.timeout(20000)]) },
    ));
    const html = await response.text();
    if (controller.signal.aborted || previewRequest !== controller || !dialog.open) return;
    frame.onload = () => {
      if (controller.signal.aborted || previewRequest !== controller || !dialog.open) return;
      status.hidden = true;
      frame.hidden = false;
      dialog.removeAttribute("aria-busy");
      byId("preview-download").disabled = false;
    };
    frame.srcdoc = html;
  } catch (error) {
    if (controller.signal.aborted || previewRequest !== controller) return;
    dialog.removeAttribute("aria-busy");
    status.textContent = `${t("reportLoadFailed")} ${explain(error.message)}`;
  }
}

byId("query-form").addEventListener("submit", query);
byId("mode-question").addEventListener("click", () => switchWorkspace("question"));
byId("mode-investigation").addEventListener("click", () => switchWorkspace("investigation"));
byId("connect").addEventListener("click", connect);
byId("access-key").addEventListener("keydown", (event) => { if (event.key === "Enter") connect(); });
document.querySelectorAll("[data-prompt-key]").forEach((button) => {
  button.addEventListener("click", () => {
    byId("prompt").value = button.dataset.prompt;
    byId("query-form").requestSubmit();
  });
});
byId("download-md").addEventListener("click", () => download("md"));
byId("download-html").addEventListener("click", () => download("html"));
byId("download-docx").addEventListener("click", () => download("docx"));
byId("download-pptx").addEventListener("click", () => download("pptx"));
byId("preview-html").addEventListener("click", openReportPreview);
byId("preview-close").addEventListener("click", closeReportPreview);
byId("report-preview").addEventListener("close", () => {
  if (!byId("report-preview").open) clearReportPreview();
});
byId("preview-download").addEventListener("click", () => download("html"));
byId("theme-toggle").addEventListener("click", () => {
  theme = theme === "dark" ? "light" : "dark";
  savePreference("aws-desk-theme", theme);
  applyTheme();
});
byId("language-toggle").addEventListener("click", () => {
  if (busy) return;
  language = language === "ko" ? "en" : "ko";
  savePreference("aws-desk-language", language);
  refreshLanguage();
});
historyPanel = createHistoryPanel({
  t, language: () => language, currentId: () => currentRun?.id, canLoad: () => connected && !busy,
  loadRun: loadSavedRun,
  fetchJson: async (url) => (await checked(await fetch(url, { headers: headers(), cache: "no-store" }))).json(),
});
investigationPanel = createInvestigationPanel({
  t, language: () => language, accounts: () => [...accounts], headers,
  onSnapshot: renderInvestigationSnapshot, onComplete: renderInvestigationResult,
  onNew: () => { if (workspaceMode === "investigation") clearInvestigationView(); },
  onChange: (state) => {
    if (workspaceMode !== "investigation") return;
    byId("stream-meta").classList.toggle("active", state.connection === "streaming" &&
      ["queued", "running"].includes(state.run?.status));
  },
});
refreshLanguage();
setBusy(false);
connect();
