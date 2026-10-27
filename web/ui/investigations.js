import { cleanNarrative, maskAccountIds } from "../presentation.js";

const lastIdKey = "aws-desk-last-investigation";
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const terminalStatuses = new Set(["complete", "partial", "failed", "cancelled", "uncertain"]);
const stepStatuses = new Set(["pending", "running", "complete", "partial", "failed", "not_requested"]);

export function investigationStepState(status) {
  return stepStatuses.has(status) ? status : "pending";
}

export function canContinueInvestigation(investigation, now = Date.now()) {
  if (!investigation || investigation.active_run_id || ["queued", "running", "uncertain"].includes(investigation.status)) return false;
  if (!Number.isFinite(Date.parse(investigation.expires_at)) || Date.parse(investigation.expires_at) <= now) return false;
  return Array.isArray(investigation.turns) && investigation.turns.length < 10;
}

export function createInvestigationController({
  fetchImpl = globalThis.fetch, headers = () => ({}), storage,
  randomUUID = () => globalThis.crypto.randomUUID(),
  onChange = () => {}, onSnapshot = () => {}, onComplete = () => {},
} = {}) {
  const state = {
    connected: false, enabled: false, loading: false, posting: false, cancelling: false,
    procedures: [], investigations: [], nextCursor: null, listLoading: false, listLoaded: false,
    investigation: null, run: null, connection: "idle", error: null, listError: null, catalogError: null,
    canRetry: false, cancelRequested: false,
  };
  let pendingRequest = null, inFlight = null, generation = 0, listGeneration = 0, connectionGeneration = 0;
  let streamGeneration = 0, streamController = null;
  const notify = () => onChange({ ...state });
  const remember = (id) => {
    try { storage?.setItem(lastIdKey, id); } catch { /* Storage is optional. */ }
  };
  const remembered = () => {
    try {
      const id = storage?.getItem(lastIdKey);
      return uuidPattern.test(id || "") ? id : null;
    } catch { return null; }
  };
  function stopStream() {
    streamGeneration++;
    streamController?.abort();
    streamController = null;
    state.connection = "idle";
  }
  async function request(url, options = {}) {
    const response = await fetchImpl(url, {
      ...options, method: options.method || "GET", cache: "no-store",
      headers: { ...headers(), ...(options.body ? { "Content-Type": "application/json" } : {}) },
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      const error = new Error(typeof body.detail === "string" ? body.detail : body.error || `HTTP${response.status}`);
      error.status = response.status;
      throw error;
    }
    return response;
  }
  async function requestJson(url, options) {
    return (await request(url, options)).json();
  }
  function accept(payload, select = true) {
    if (!payload?.investigation || !uuidPattern.test(payload.investigation.id || "") ||
        !payload.run || !uuidPattern.test(payload.run.id || "") ||
        payload.run.investigation_id !== payload.investigation.id ||
        !Array.isArray(payload.run.evidence) || !Array.isArray(payload.investigation.turns)) {
      throw new Error("InvalidInvestigationSnapshot");
    }
    state.investigation = payload.investigation;
    remember(payload.investigation.id);
    if (pendingRequest && payload.investigation.turns.some((turn) => turn.id === pendingRequest.body.request_id)) {
      pendingRequest = null;
      state.canRetry = false;
    }
    if (select || state.run?.id === payload.run.id) {
      // A snapshot is the entire public state, never a delta.
      state.run = { ...payload.run, evidence: [...payload.run.evidence] };
      state.error = null;
      onSnapshot({ investigation: state.investigation, run: state.run });
      if (state.run.result) onComplete(state.run.result);
    }
    notify();
  }
  async function stream(investigationId, runId) {
    stopStream();
    const token = streamGeneration;
    const controller = new AbortController();
    streamController = controller;
    state.connection = "streaming";
    notify();
    let reader, finished = false;
    try {
      const response = await request(
        `/api/investigations/${encodeURIComponent(investigationId)}/turns/${encodeURIComponent(runId)}/events`,
        { signal: controller.signal },
      );
      if (token !== streamGeneration) { await response.body?.cancel(); return; }
      if (!response.body) throw new Error("EventStreamDisconnected");
      reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (token === streamGeneration) {
        const { value, done } = await reader.read();
        buffer = (buffer + decoder.decode(value, { stream: !done })).replace(/\r\n/g, "\n");
        if (buffer.length > 4_000_000) throw new Error("ResponseTooLarge");
        let boundary;
        while ((boundary = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const data = frame.split("\n").filter((line) => line.startsWith("data:"))
            .map((line) => line.slice(5).trimStart()).join("\n");
          if (!data || token !== streamGeneration) continue;
          const event = JSON.parse(data);
          if (event.type === "error") throw new Error(event.code || "InvestigationStreamFailed");
          if (event.type === "snapshot") {
            if (event.investigation?.id !== investigationId || event.run?.id !== runId) {
              throw new Error("InvalidInvestigationSnapshot");
            }
            accept(event, false);
            finished = terminalStatuses.has(event.run.status);
          }
          if (event.type === "complete") {
            if (event.id !== runId) throw new Error("InvalidInvestigationSnapshot");
            finished = true;
            if (state.run?.id === runId) {
              state.run = { ...state.run, status: event.status, answer: event.answer,
                evidence: [...(event.evidence || [])], result: event };
              onComplete(event);
            }
          }
        }
        if (done) break;
      }
      if (token !== streamGeneration) return;
      if (!finished) throw new Error("EventStreamDisconnected");
      state.connection = "complete";
    } catch (error) {
      if (token !== streamGeneration || controller.signal.aborted) return;
      state.error = error.message;
      state.connection = "disconnected";
    } finally {
      await reader?.cancel().catch(() => {});
      if (token === streamGeneration) {
        streamController = null;
        notify();
      }
    }
  }
  function watchCurrent() {
    if (state.run && !terminalStatuses.has(state.run.status)) {
      void stream(state.investigation.id, state.run.id);
    } else {
      state.connection = "complete";
      notify();
    }
  }
  async function open(id) {
    if (!uuidPattern.test(id || "")) return;
    const token = ++generation;
    stopStream();
    state.loading = true;
    state.error = null;
    state.cancelRequested = false;
    notify();
    try {
      const payload = await requestJson(`/api/investigations/${encodeURIComponent(id)}`);
      if (token !== generation) return;
      if (payload.investigation?.id !== id) throw new Error("InvalidInvestigationSnapshot");
      accept(payload);
      watchCurrent();
    } catch (error) {
      if (token === generation) state.error = error.message;
    } finally {
      if (token === generation) { state.loading = false; notify(); }
    }
  }
  async function refresh(reset = true) {
    if (state.listLoading || (!reset && !state.nextCursor)) return;
    const token = ++listGeneration;
    state.listLoading = true;
    state.listError = null;
    notify();
    try {
      const cursor = !reset ? `&cursor=${encodeURIComponent(state.nextCursor)}` : "";
      const page = await requestJson(`/api/investigations?limit=10${cursor}`);
      if (token !== listGeneration) return;
      if (!Array.isArray(page.investigations) || page.investigations.length > 20) throw new Error("InvalidInvestigationPage");
      const items = reset ? page.investigations : [...state.investigations, ...page.investigations];
      state.investigations = [...new Map(items.map((item) => [item.id, item])).values()].slice(0, 100);
      state.nextCursor = state.investigations.length >= 100 ? null : page.next_cursor || null;
      state.listLoaded = true;
    } catch (error) {
      if (token === listGeneration) state.listError = error.message;
    } finally {
      if (token === listGeneration) { state.listLoading = false; notify(); }
    }
  }
  async function connect() {
    const token = ++connectionGeneration;
    state.connected = true;
    state.catalogError = null;
    notify();
    try {
      const catalog = await requestJson("/api/procedures");
      if (token !== connectionGeneration) return;
      if (!Array.isArray(catalog.procedures)) throw new Error("InvalidProcedureCatalog");
      state.procedures = catalog.procedures;
      state.enabled = catalog.enabled === true;
    } catch (error) {
      if (token !== connectionGeneration) return;
      state.enabled = false;
      state.catalogError = error.message;
    }
    notify();
    const id = state.investigation?.id || remembered();
    await Promise.all([refresh(), ...(id ? [open(id)] : [])]);
  }
  async function sendPending() {
    if (!pendingRequest) return;
    const submitted = pendingRequest, token = ++generation;
    state.posting = true;
    state.canRetry = false;
    state.error = null;
    notify();
    try {
      const payload = await requestJson(submitted.url, { method: "POST", body: JSON.stringify(submitted.body) });
      if (token !== generation) return;
      if (payload.run?.id !== submitted.body.request_id) throw new Error("InvalidInvestigationSnapshot");
      pendingRequest = null;
      state.cancelRequested = false;
      accept(payload);
      watchCurrent();
      if (state.connected) void refresh();
    } catch (error) {
      if (token === generation) {
        state.error = error.message;
        // The same request ID is retained in memory for an explicit retry.
        const rejected = [400, 401, 403, 404, 413, 422].includes(error.status);
        state.canRetry = !rejected;
        if (rejected) pendingRequest = null;
      }
    } finally {
      if (token === generation) { state.posting = false; notify(); }
      inFlight = null;
    }
  }
  function submit({ procedureId, prompt, language }) {
    if (inFlight) return inFlight;
    if (pendingRequest) return Promise.resolve();
    if (!prompt?.trim() || prompt.trim().length > 4000) return Promise.resolve();
    if (state.investigation && !canContinueInvestigation(state.investigation)) return Promise.resolve();
    const requestId = randomUUID();
    pendingRequest = {
      url: state.investigation ? `/api/investigations/${encodeURIComponent(state.investigation.id)}/turns` : "/api/investigations",
      body: { request_id: requestId, ...(state.investigation ? {} : { procedure_id: procedureId }),
        prompt: prompt.trim(), language: language === "en" ? "en" : "ko" },
    };
    // Remembering the reservation ID also recovers a lost creation response after a reload.
    if (!state.investigation) remember(requestId);
    inFlight = sendPending();
    return inFlight;
  }
  async function openTurn(id) {
    if (!state.investigation || !uuidPattern.test(id || "")) return;
    const investigationId = state.investigation.id, token = ++generation;
    state.loading = true;
    state.error = null;
    notify();
    try {
      const payload = await requestJson(
        `/api/investigations/${encodeURIComponent(investigationId)}/turns/${encodeURIComponent(id)}`,
      );
      if (token !== generation) return;
      if (payload.investigation?.id !== investigationId || payload.run?.id !== id) throw new Error("InvalidInvestigationSnapshot");
      accept(payload);
    } catch (error) {
      if (token === generation) state.error = error.message;
    } finally {
      if (token === generation) { state.loading = false; notify(); }
    }
  }
  async function cancel() {
    const investigationId = state.investigation?.id, runId = state.investigation?.active_run_id;
    if (!runId || state.cancelling || state.cancelRequested) return;
    state.cancelling = true;
    state.error = null;
    notify();
    try {
      await requestJson(`/api/investigations/${encodeURIComponent(investigationId)}/turns/${encodeURIComponent(runId)}/cancel`,
        { method: "POST", body: "{}" });
      if (state.investigation?.id === investigationId) state.cancelRequested = true;
    } catch (error) { state.error = error.message; }
    finally { state.cancelling = false; notify(); }
  }
  return {
    getState: () => ({ ...state }), connect, open, openTurn, refresh, submit, cancel,
    reconnect: () => state.investigation ? open(state.investigation.id) : remembered() ? open(remembered()) : Promise.resolve(),
    retry() {
      if (inFlight || !pendingRequest) return inFlight || Promise.resolve();
      inFlight = sendPending();
      return inFlight;
    },
    disconnect() {
      connectionGeneration++;
      generation++;
      listGeneration++;
      stopStream();
      state.connected = false;
      state.loading = false;
      state.posting = false;
      state.canRetry = Boolean(pendingRequest);
      state.listLoading = false;
      notify();
    },
    newInvestigation() {
      if (state.posting) return;
      generation++;
      stopStream();
      state.investigation = null;
      state.run = null;
      state.loading = false;
      state.error = null;
      state.cancelRequested = false;
      pendingRequest = null;
      state.canRetry = false;
      try { storage?.removeItem(lastIdKey); } catch { /* Storage is optional. */ }
      notify();
    },
  };
}

export function createInvestigationPanel({
  t, language, accounts, headers, onSnapshot, onComplete, onChange = () => {}, onNew = () => {},
}) {
  const byId = (id) => document.getElementById(id);
  let selectedProcedureId = "", disabled = true;
  let storage;
  try { storage = globalThis.localStorage; } catch { /* Storage is optional. */ }
  const text = (value) => cleanNarrative(maskAccountIds(String(value || ""), accounts(), { strict: true }));
  const localized = (value) => text(typeof value === "string" ? value : value?.[language()] || value?.ko || value?.en || "");
  const statusText = (status) => t(`investigationStatus_${status || "queued"}`);
  const errorText = (code) => t(code) === code ? t("investigationError", { code: text(code) }) : t(code);
  function dateText(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "" : new Intl.DateTimeFormat(language() === "en" ? "en-GB" : "ko-KR", {
      dateStyle: "short", timeStyle: "short", timeZone: "Asia/Seoul", hour12: false,
    }).format(date) + " KST";
  }
  const controller = createInvestigationController({
    headers, storage, onSnapshot, onComplete, onChange(state) { render(state); onChange(state); },
  });
  function render(state = controller.getState()) {
    const locked = disabled || !state.connected || state.loading || state.posting;
    const procedure = state.investigation?.procedure || state.procedures.find((item) => item.id === selectedProcedureId) || state.procedures[0];
    if (procedure) selectedProcedureId = procedure.id;
    const picker = byId("procedure-picker");
    picker.replaceChildren();
    for (const item of state.procedures) {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = localized(item.name);
      option.selected = item.id === procedure?.id;
      picker.append(option);
    }
    picker.disabled = locked || Boolean(state.investigation) || !state.enabled;
    byId("procedure-description").textContent = localized(procedure?.description);
    byId("procedure-version").textContent = procedure ? t("procedureVersion", { version: text(procedure.version) }) : "";
    byId("investigation-title").textContent = state.investigation ? text(state.investigation.title) : t("newInvestigation");
    byId("investigation-prompt-label").textContent = t(state.investigation ? "investigationFollowup" : "investigationQuestion");
    byId("investigation-submit").textContent = t(state.posting ? "investigationSending" : state.investigation ? "investigationContinue" : "investigationStart");
    const cannotContinue = state.investigation && !canContinueInvestigation(state.investigation);
    byId("investigation-submit").disabled = locked || !state.enabled || !procedure || cannotContinue || state.canRetry;
    byId("investigation-prompt").disabled = locked || cannotContinue || state.canRetry;
    byId("investigation-new").disabled = locked;
    byId("investigation-retry").hidden = !state.canRetry;
    byId("investigation-retry").disabled = locked;
    byId("investigation-reconnect").hidden = !state.investigation;
    byId("investigation-reconnect").disabled = locked;
    byId("investigation-cancel").hidden = !state.investigation?.active_run_id;
    byId("investigation-cancel").disabled = locked || state.cancelling || state.cancelRequested;
    byId("investigation-cancel").textContent = t(state.cancelRequested ? "investigationCancelRequested" : "investigationCancel");
    let note = "";
    if (state.investigation?.status === "uncertain") note = t("investigationUncertain");
    else if (state.investigation && Date.parse(state.investigation.expires_at) <= Date.now()) note = t("investigationExpired");
    else if (state.investigation?.turns?.length >= 10) note = t("investigationTurnLimit");
    else if (state.investigation?.active_run_id) note = t("investigationActive");
    byId("investigation-note").textContent = note;
    byId("investigation-error").textContent = state.error ? errorText(state.error)
      : state.catalogError ? errorText(state.catalogError) : state.connected && !state.enabled ? t("investigationUnavailable") : "";
    byId("investigation-connection").textContent = state.loading ? t("investigationLoading")
      : state.connection === "disconnected" ? t("investigationDisconnected")
      : state.connection === "streaming" ? t("investigationConnected") : "";
    const steps = byId("procedure-steps");
    steps.replaceChildren();
    for (const step of procedure?.steps || []) {
      const observed = state.run?.procedure_steps?.find((item) => item.id === step.id);
      const status = investigationStepState(observed?.status);
      const item = document.createElement("li");
      item.dataset.status = status;
      const name = document.createElement("span"), badge = document.createElement("span");
      name.textContent = localized(step.label);
      badge.textContent = t(`investigationStep_${status}`);
      badge.className = `step-status ${status}`;
      item.append(name, badge);
      steps.append(item);
    }
    const turns = byId("investigation-turns");
    turns.replaceChildren();
    byId("investigation-turn-history").hidden = !state.investigation;
    for (const [index, turn] of (state.investigation?.turns || []).entries()) {
      const item = document.createElement("li"), button = document.createElement("button");
      button.type = "button";
      button.className = `history-item${state.run?.id === turn.id ? " selected" : ""}`;
      button.dataset.turnId = turn.id;
      button.setAttribute("aria-current", String(state.run?.id === turn.id));
      button.disabled = locked;
      const prompt = document.createElement("strong"), meta = document.createElement("small");
      prompt.textContent = `${index + 1}. ${text(turn.prompt)}`;
      meta.textContent = `${statusText(turn.status)} / ${dateText(turn.created_at)}`;
      button.append(prompt, meta);
      button.addEventListener("click", () => controller.openTurn(turn.id));
      item.append(button);
      turns.append(item);
    }
    const list = byId("investigation-list");
    list.replaceChildren();
    byId("investigation-list-status").textContent = state.listError ? errorText(state.listError)
      : state.listLoading ? t("investigationLoading") : state.listLoaded && !state.investigations.length ? t("investigationEmpty") : "";
    byId("investigation-refresh").disabled = locked || state.listLoading;
    byId("investigation-more").hidden = !state.nextCursor;
    byId("investigation-more").disabled = locked || state.listLoading;
    for (const listed of state.investigations) {
      const investigation = listed.id === state.investigation?.id ? state.investigation : listed;
      const item = document.createElement("li"), button = document.createElement("button");
      button.type = "button";
      button.dataset.investigationId = investigation.id;
      button.className = `history-item${state.investigation?.id === investigation.id ? " selected" : ""}`;
      button.disabled = locked;
      const title = document.createElement("strong"), meta = document.createElement("small");
      title.textContent = text(investigation.title) || t("newInvestigation");
      meta.textContent = `${statusText(investigation.status)} / ${dateText(investigation.updated_at || investigation.created_at)}`;
      button.append(title, meta);
      button.addEventListener("click", () => controller.open(investigation.id));
      item.append(button);
      list.append(item);
    }
  }
  byId("procedure-picker").addEventListener("change", (event) => { selectedProcedureId = event.target.value; render(); });
  byId("investigation-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (byId("investigation-submit").disabled) return;
    const input = byId("investigation-prompt"), value = input.value;
    await controller.submit({ procedureId: selectedProcedureId, prompt: value, language: language() });
    const state = controller.getState();
    if (!state.canRetry && !state.error && input.value === value) input.value = "";
  });
  byId("investigation-new").addEventListener("click", () => {
    controller.newInvestigation();
    byId("investigation-prompt").value = "";
    onNew();
    byId("investigation-prompt").focus();
  });
  byId("investigation-retry").addEventListener("click", () => controller.retry());
  byId("investigation-cancel").addEventListener("click", () => controller.cancel());
  byId("investigation-reconnect").addEventListener("click", () => controller.reconnect());
  byId("investigation-refresh").addEventListener("click", () => controller.refresh());
  byId("investigation-more").addEventListener("click", () => controller.refresh(false));
  return { ...controller, render, setDisabled(value) { disabled = value; render(); } };
}
