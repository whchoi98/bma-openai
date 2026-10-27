import { randomUUID } from "node:crypto";
import { setTimeout as wait } from "node:timers/promises";
import { BmaClient } from "./bma.js";
import { publicItems } from "./evidence.js";
import { cleanMarkdownProse } from "./presentation.js";
import { procedureInstructions, procedureSteps } from "./procedures.js";
import { SampleRunner } from "./runners.js";
import { summarize } from "./reports.js";
import { buildInvestigationReport, investigationMarker, mutateRecord, selectTurnItems, turnMarker } from "./investigation-records.js";
import contract from "./contract.json" with { type: "json" };

const TERMINAL = new Set(["complete", "partial", "failed", "cancelled", "uncertain"]);
const LEASE_MS = 45_000, HEARTBEAT_MS = 10_000, SNAPSHOT_MS = 1000;
const COMPLETED = new Set(["agent.session.turn.completed", "agent.session.completed"]);
const FAILED = new Set(["agent.session.turn.failed", "agent.session.failed", "agent.session.environment.failed"]);
const CANCELLED = new Set(["agent.session.turn.cancelled"]);
const publicPhase = (item) => [undefined, null, "final", "final_answer"].includes(item.phase);
const publicMessage = (item) => item?.type === "message" && item.role === "assistant" &&
  [undefined, null, "final"].includes(item.channel) && publicPhase(item);
const hasFinalText = (item) => publicMessage(item) && item.status === "completed" &&
  item.content?.some((content) => content.type === "output_text" && typeof content.text === "string" && content.text);
const distinct = (values) => [...new Set(values)];

class ExecutionStop extends Error {
  constructor(code, status = "failed") { super(code); this.code = code; this.status = status; }
}

const codeOf = (error) => error instanceof ExecutionStop ? error.code :
  typeof error?.code === "string" && /^[A-Z][A-Za-z0-9]{0,63}$/.test(error.code) ? error.code : "InvestigationExecutionFailed";

class Execution {
  constructor(dependencies, ids, session, turn) {
    Object.assign(this, dependencies, ids);
    this.clock = dependencies.clock || Date.now;
    this.sleep = dependencies.sleep || ((ms, signal) => wait(ms, undefined, { signal }));
    this.session = session;
    this.turn = turn;
    this.token = randomUUID();
    this.controller = new AbortController();
    this.watchController = new AbortController();
    this.stopPromise = new Promise((resolve) => { this.resolveStop = resolve; });
    this.snapshot = { answer: turn.answer || "", evidence: turn.evidence || [], errors: turn.errors || [] };
    this.items = new Map();
    this.writeQueue = Promise.resolve();
    this.lastSave = this.clock();
    this.lastHeartbeat = this.clock();
    this.dirty = false;
    this.running = true;
    this.verifiedSession = false;
    this.cancelSent = false;
    this.deadline = Math.min(Date.parse(turn.deadline_at), Date.parse(turn.created_at) + 300_000);
    if (!Number.isFinite(this.deadline)) throw new Error("InvalidInvestigationDeadline");
  }
  iso(time = this.clock()) { return new Date(time).toISOString(); }
  stop(error) {
    if (this.stopped) return;
    this.stopped = error;
    this.controller.abort();
    this.resolveStop(error);
  }
  async guard(promise) {
    if (this.stopped) throw this.stopped;
    return Promise.race([promise, this.stopPromise.then((error) => { throw error; })]);
  }
  check() {
    if (this.stopped) throw this.stopped;
    if (this.turn.cancel_requested) throw new ExecutionStop("CancelledByUser", "cancelled");
    if (this.clock() >= this.deadline) throw new ExecutionStop("InvestigationDeadlineExceeded");
  }
  async persist(kind, id, fn) {
    try {
      const saved = await mutateRecord(this.store, kind, id, fn);
      if (saved?.warning) {
        this.snapshot.errors.push("InvestigationIndexWriteFailed");
        this.dirty = true;
      }
      return saved;
    }
    catch (error) { error.investigationStorageFailure = true; throw error; }
  }
  save(patch) {
    const pending = this.writeQueue.then(async () => {
      const saved = await this.persist("Turn", this.run_id, (current) => {
        if (current.worker_token !== this.token) return null;
        return { ...current, ...(typeof patch === "function" ? patch(current) : patch), updated_at: this.iso() };
      });
      if (!saved) throw new ExecutionStop("InvestigationLeaseLost");
      this.turn = saved.value;
      return saved;
    });
    this.writeQueue = pending.catch(() => {});
    return pending;
  }
  snapshotPatch() {
    return { answer: cleanMarkdownProse(this.snapshot.answer), evidence: structuredClone(this.snapshot.evidence),
      errors: distinct(this.snapshot.errors),
      procedure_steps: procedureSteps(this.session.procedure, this.snapshot.evidence, "running") };
  }
  async flush(heartbeat = false) {
    const time = this.clock();
    if (!this.running || (!heartbeat && (!this.dirty || time - this.lastSave < SNAPSHOT_MS))) return;
    const patch = {};
    if (!this.finalizing && this.dirty && time - this.lastSave >= SNAPSHOT_MS) {
      Object.assign(patch, this.snapshotPatch());
      this.lastSave = time; this.dirty = false;
    }
    if (heartbeat) {
      patch.lease_until = this.iso(time + LEASE_MS);
      this.lastHeartbeat = time;
    }
    if (Object.keys(patch).length) await this.save(patch);
  }
  async watchdog() {
    try {
      while (this.running) {
        await this.sleep(SNAPSHOT_MS, this.watchController.signal);
        if (!this.running) return;
        const stored = await this.store.getTurn(this.run_id);
        if (!stored || stored.value.worker_token !== this.token) throw new ExecutionStop("InvestigationLeaseLost");
        this.turn.cancel_requested = stored.value.cancel_requested;
        if (!this.finalizing) this.check();
        await this.flush(this.clock() - this.lastHeartbeat >= HEARTBEAT_MS);
      }
    } catch (error) {
      if (this.running) {
        if (!(error instanceof ExecutionStop)) error.investigationStorageFailure = true;
        this.stop(error);
      }
    }
  }
  async cancel() {
    if (this.settings.mode !== "live" || this.finalizing || this.scopeRejected ||
        !this.session.bma_session_id || this.cancelSent) return;
    this.cancelSent = true;
    const signal = AbortSignal.timeout(15_000), proof = this.makeClient({ signal });
    if (!this.verifiedSession) {
      try {
        this.validateSession(await proof.getSession(this.session.bma_session_id));
        this.verifiedSession = true;
      } catch {
        this.cancelFailed = true; this.snapshot.errors.push("CancelStateUncertain");
        return;
      }
    }
    try { await (this.client || proof).cancel(this.session.bma_session_id); }
    catch {
      this.cancelFailed = true; this.snapshot.errors.push("CancelRequestFailed");
      return;
    }
    // Cancellation is asynchronous. Only bounded metadata reads are allowed
    // after cancellation; no more input, tool observations or model requests.
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const state = this.validateSession(await proof.getSession(this.session.bma_session_id));
        if (["idle", "failed"].includes(state.status)) return;
        if (attempt < 2) await this.sleep(SNAPSHOT_MS, signal);
      } catch { break; }
    }
    this.cancelFailed = true; this.snapshot.errors.push("CancelStateUncertain");
  }
  validateSession(value) {
    if (!value || value.id !== this.session.bma_session_id ||
        value.agent?.model !== this.settings.model ||
        value.role_arn !== this.settings.sessionRoleArn ||
        value.environment?.runtime_arn !== this.settings.runtimeArn ||
        typeof value.agent?.instructions !== "string" ||
        !value.agent.instructions.includes(investigationMarker(this.investigation_id))) {
      this.scopeRejected = true;
      throw new ExecutionStop("InvestigationSessionScopeMismatch");
    }
    return value;
  }
  async readSession() {
    this.check();
    const response = await this.guard(this.client.getSession(this.session.bma_session_id));
    this.verifiedSession = false;
    const value = this.validateSession(response);
    this.verifiedSession = true;
    return value;
  }
  async findSession() {
    const marker = investigationMarker(this.investigation_id), found = new Map(), seen = new Set();
    let after, checked = 0;
    for (let page = 0; page < 5; page++) {
      this.check();
      const response = await this.guard(this.client.listSessions({ after }));
      if (!Array.isArray(response?.data) || response.data.length > 100) throw new ExecutionStop("InvalidSessionPage", "uncertain");
      for (const candidate of response.data) {
        if (++checked > 500) throw new ExecutionStop("SessionSearchIncomplete", "uncertain");
        if (candidate?.agent?.instructions?.includes(marker)) found.set(candidate.id, candidate);
      }
      if (!response.has_more) {
        if (found.size > 1) throw new ExecutionStop("DuplicateInvestigationSessions", "uncertain");
        return found.size === 1 ? [...found.keys()][0] : null;
      }
      if (typeof response.last_id !== "string" || !response.last_id || seen.has(response.last_id)) {
        throw new ExecutionStop("SessionSearchIncomplete", "uncertain");
      }
      seen.add(response.last_id); after = response.last_id;
    }
    throw new ExecutionStop("SessionSearchIncomplete", "uncertain");
  }
  async reconcileSession() {
    try { return await this.findSession(); }
    catch (error) {
      if (error instanceof ExecutionStop || error.investigationStorageFailure) throw error;
      throw new ExecutionStop("SessionCreationUncertain", "uncertain");
    }
  }
  async ensureSession() {
    if (!this.session.bma_session_id) {
      let id;
      if (this.turn.phase === "queued") {
        await this.save({ phase: "creating_session" });
        this.check();
        try {
          id = await this.guard(this.client.createInvestigationSession(
            `${investigationMarker(this.investigation_id)}\n${procedureInstructions(this.session.procedure, this.turn.language)}`,
            this.turn.language));
        } catch (error) {
          if (error instanceof ExecutionStop || error.investigationStorageFailure) throw error;
          id = await this.reconcileSession();
        }
      } else id = await this.reconcileSession();
      if (typeof id !== "string" || !id || id.length > 256) throw new ExecutionStop("SessionCreationUncertain", "uncertain");
      const saved = await this.persist("Session", this.investigation_id, (current) => {
        if (current.active_run_id !== this.run_id || (current.bma_session_id && current.bma_session_id !== id)) {
          throw new ExecutionStop("InvestigationSessionChanged");
        }
        return { ...current, bma_session_id: id, updated_at: this.iso(), status: "running" };
      });
      this.session = saved.value;
    }
    let current;
    try { current = await this.readSession(); }
    catch (error) {
      if (error instanceof ExecutionStop || error.investigationStorageFailure) throw error;
      throw new ExecutionStop("SessionVerificationUncertain", "uncertain");
    }
    if (current.status === "failed") throw new ExecutionStop("BmaSessionFailed");
  }
  parseItems(items) {
    const current = items.filter((item) => item?.turn_id === this.turn.bma_turn_id);
    for (const item of current) {
      if (item.type === "mcp_call" &&
          (item.server_label !== "seoul_aws" || !contract.tools.includes(item.name))) {
        throw new ExecutionStop("ForbiddenInvestigationTool");
      }
      if (typeof item.id !== "string" || !item.id) throw new ExecutionStop("MissingItemIdentity");
      this.items.set(item.id, item);
    }
    if (this.items.size > 500) throw new ExecutionStop("ItemLimitReached");
    const values = [...this.items.values()];
    if (values.filter((item) => item.type === "mcp_call").length >= 30) throw new ExecutionStop("ToolCallLimitReached");
    const parsed = publicItems(values.filter((item) =>
      (item.type !== "mcp_call" || item.status === "completed") &&
      (item.role !== "assistant" || publicMessage(item))), this.settings);
    if (parsed.evidence_errors.length) throw new ExecutionStop(parsed.evidence_errors[0]);
    if (parsed.evidence.some((item) => item.status === "account_mismatch")) throw new ExecutionStop("RuntimeAccountMismatch");
    if (parsed.evidence.some((item) => item.api_calls.some((call) => call.api === "GetCallerIdentity" && call.success === false) ||
        (item.tool === "get_account_context" && item.data.some((row) => row.account_verified === false)))) {
      throw new ExecutionStop("RuntimeIdentityVerificationFailed");
    }
    if (parsed.answer) this.snapshot.answer = parsed.answer;
    const evidence = new Map(this.snapshot.evidence.map((item) => [item.item_id || item.tool, item]));
    for (const item of parsed.evidence) evidence.set(item.item_id || item.tool, item);
    this.snapshot.evidence = [...evidence.values()];
    this.dirty = true;
    return current;
  }
  async readItems() {
    this.check();
    const response = await this.guard(this.client.listItems(this.session.bma_session_id));
    if (!Array.isArray(response?.items) || response.items.length > 500 || response.complete !== true) {
      throw new ExecutionStop("ItemsPartiallyRetrieved", "uncertain");
    }
    let selected;
    try { selected = selectTurnItems(response.items, this.run_id); }
    catch (error) { throw new ExecutionStop(error.message === "DuplicateTurnInput" ? "DuplicateTurnInput" : "MissingTurnIdentity", "uncertain"); }
    if (!selected) return null;
    if (this.turn.bma_turn_id && this.turn.bma_turn_id !== selected.turnId) {
      throw new ExecutionStop("InvestigationTurnChanged", "uncertain");
    }
    if (!this.turn.bma_turn_id) await this.save({ bma_turn_id: selected.turnId });
    this.parseItems(selected.items);
    return selected.items;
  }
  async ensureInput() {
    if (["queued", "creating_session"].includes(this.turn.phase)) {
      await this.save({ phase: "submitting" });
      this.check();
      try {
        await this.guard(this.client.submitInput(this.session.bma_session_id,
          `${turnMarker(this.run_id)}\nRespond in ${this.turn.language === "en" ? "English" : "Korean"}.\nCurrent UTC time: ${this.iso()}\n${this.turn.prompt}`));
      } catch (error) {
        if (error instanceof ExecutionStop || error.investigationStorageFailure) throw error;
        // The durable user item is the only proof of acceptance. Never repeat POST.
      }
    }
    for (let attempt = 0; attempt < 3; attempt++) {
      let items;
      try { items = await this.readItems(); }
      catch (error) {
        if (error instanceof ExecutionStop || error.investigationStorageFailure) throw error;
        throw new ExecutionStop("SubmissionUncertain", "uncertain");
      }
      if (items) {
        await this.save({ phase: "running" });
        return;
      }
      if (attempt < 2) await this.guard(this.sleep(SNAPSHOT_MS, this.controller.signal));
    }
    throw new ExecutionStop("SubmissionUncertain", "uncertain");
  }
  async events() {
    let partial = "";
    try {
      for await (const event of this.client.events(this.session.bma_session_id)) {
        if (!this.running || this.finalizing || this.stopped) return;
        this.check();
        const turnId = event.turn_id || event.turn?.id || event.item?.turn_id;
        if (turnId !== this.turn.bma_turn_id) continue;
        if (event.type === "agent.session.turn.item.done" && event.item) {
          this.parseItems([{ ...event.item, status: event.item.status ?? "completed" }]);
        } else if (event.type === "agent.session.turn.output_text.delta" &&
            [undefined, null, "final"].includes(event.channel) && publicPhase(event) && typeof event.delta === "string") {
          partial += event.delta;
          if (partial.length > 60_000) throw new ExecutionStop("AnswerTooLarge");
          // A reconnected stream may replay its prefix. Replace only when the
          // stream proves it extends the persisted snapshot; never append twice.
          if (!this.snapshot.answer || partial.startsWith(this.snapshot.answer)) {
            this.snapshot.answer = partial; this.dirty = true;
          }
        } else if (FAILED.has(event.type)) throw new ExecutionStop("BmaTurnFailed");
        else if (CANCELLED.has(event.type)) throw new ExecutionStop("BmaTurnCancelled", "cancelled");
        else if (COMPLETED.has(event.type)) this.streamCompleted = true;
        await this.flush();
      }
    } catch (error) {
      if (!this.running) return;
      if (error instanceof ExecutionStop || error.investigationStorageFailure) this.stop(error);
      // Durable polling owns recovery from an interrupted event connection.
    }
  }
  async live() {
    this.client = this.makeClient({ signal: this.controller.signal });
    await this.ensureSession();
    await this.ensureInput();
    this.eventTask = this.events();
    while (true) {
      this.check();
      const session = await this.readSession();
      const items = await this.readItems();
      if (!items) throw new ExecutionStop("MissingTurnIdentity", "uncertain");
      if (session.status === "failed") throw new ExecutionStop("BmaTurnFailed");
      const pendingTools = [...this.items.values()].some((item) => item.type === "mcp_call" && item.status !== "completed");
      if (session.status === "idle" && !pendingTools && (items.some(hasFinalText) || this.streamCompleted)) return "complete";
      await this.flush();
      await this.guard(this.sleep(SNAPSHOT_MS, this.controller.signal));
    }
  }
  async previousReport() {
    const position = this.session.turns.findIndex((item) => item.id === this.run_id);
    if (position <= 0) return null;
    try { return await this.reportStore.get(this.session.turns[position - 1].id); }
    catch (error) { error.investigationStorageFailure = true; throw error; }
  }
  async sample() {
    await this.save({ phase: "running" });
    const previous = await this.previousReport();
    if (previous && !/\b(?:ec2|rds|ecs|lambda|cloudwatch|alarm|vpc|ebs|ecr|s3|dynamodb|elasticache|valkey|redis|opensearch|msk|kafka)\b|알람|람다/i.test(this.turn.prompt)) {
      this.snapshot.answer = summarize(previous.evidence || [], this.turn.language);
      this.snapshot.evidence = [];
      return "complete";
    }
    for await (const event of new SampleRunner().stream(this.turn.prompt, { language: this.turn.language })) {
      this.check();
      if (event.type === "tool_result") this.snapshot.evidence.push(event.result);
      if (event.type === "result") {
        this.snapshot = { answer: event.answer, evidence: event.evidence, errors: event.errors };
        return event.status;
      }
      this.dirty = true;
      await this.flush();
    }
    throw new ExecutionStop("SampleExecutionIncomplete");
  }
  async syncSession(status) {
    const saved = await this.persist("Session", this.investigation_id, (current) => ({
      ...current, updated_at: this.iso(),
      ...(current.active_run_id === this.run_id ? {
        status, active_run_id: status === "uncertain" ? this.run_id : null,
      } : {}),
      turns: current.turns.map((item) => item.id === this.run_id ? { ...item, status } : item),
    }));
    this.session = saved.value;
    if (saved.warning && TERMINAL.has(this.turn.status)) {
      const updated = await this.persist("Turn", this.run_id, (current) => ({
        ...current, errors: distinct([...(current.errors || []), "InvestigationIndexWriteFailed"]),
      }));
      this.turn = updated.value;
    }
  }
  async finish(status) {
    this.finalizing = true;
    this.controller.abort();
    await this.writeQueue;
    await this.save({ ...this.snapshotPatch(), phase: "finalizing", final_status: status });
    const previous = await this.previousReport();
    const record = buildInvestigationReport({ ...this.turn, ...this.snapshotPatch(), status },
      this.session, this.settings, previous);
    let terminal = ["cancelled", "uncertain", "failed"].includes(status) ? status : record.status;
    let existing;
    try { existing = await this.reportStore.get(record.id); }
    catch (error) { error.investigationStorageFailure = true; throw error; }
    const conflict = existing && ["id", "investigation_id", "prompt", "language", "account_id",
      "app_region", "target_region", "mode"].some((key) => existing[key] !== record[key]);
    if (conflict) {
      this.snapshot.errors.push("ReportIdConflict");
      record.errors = distinct([...record.errors, "ReportIdConflict"]);
      record.status = "failed";
      record.report_available = false;
      terminal = "failed";
    }
    record.procedure_steps = procedureSteps(this.session.procedure, record.evidence, terminal);
    try { if (!conflict) await this.reportStore.put(record); }
    catch (error) {
      if (!error.recordSaved) { error.investigationStorageFailure = true; throw error; }
      this.snapshot.errors.push("ReportIndexWriteFailed");
    }
    await this.save({ status: terminal, phase: "finalizing", final_status: undefined,
      answer: record.answer, evidence: record.evidence, errors: distinct([...record.errors, ...this.snapshot.errors]),
      procedure_steps: procedureSteps(this.session.procedure, record.evidence, terminal),
      result: record, lease_until: this.iso() });
    await this.syncSession(terminal);
    return this.turn;
  }
  async run() {
    this.makeClient = this.bmaFactory || ((options) => new BmaClient(this.settings, options));
    const claimed = await this.persist("Turn", this.run_id, (current) => {
      if (TERMINAL.has(current.status) ||
          (current.worker_token && Date.parse(current.lease_until) > this.clock())) return null;
      return { ...current, worker_token: this.token, lease_until: this.iso(this.clock() + LEASE_MS),
        status: "running", updated_at: this.iso() };
    });
    if (!claimed) return { status: "duplicate", id: this.run_id };
    this.turn = claimed.value;
    this.finalizing = this.turn.phase === "finalizing" && Boolean(this.turn.final_status);
    this.watchTask = this.watchdog();
    try {
      if (!this.finalizing) this.check();
      const status = this.finalizing ? this.turn.final_status :
        this.settings.mode === "sample" ? await this.sample() : await this.live();
      return await this.finish(status);
    } catch (error) {
      if (error.code === "InvestigationLeaseLost") return { status: "duplicate", id: this.run_id };
      try {
        // Fence cancellation with an atomic ownership check and a fresh lease.
        // The bounded cancellation/proof requests finish before this lease expires.
        await this.save(() => ({ lease_until: this.iso(this.clock() + LEASE_MS) }));
        await this.cancel();
        if (error.investigationStorageFailure) throw error;
        this.snapshot.errors.push(codeOf(error));
        return await this.finish(this.cancelFailed ? "uncertain" : error instanceof ExecutionStop ? error.status : "failed");
      } catch (failure) {
        if (failure.code === "InvestigationLeaseLost") return { status: "duplicate", id: this.run_id };
        throw failure;
      }
    } finally {
      this.running = false;
      this.controller.abort();
      this.watchController.abort();
    }
  }
}

export async function executeInvestigation(dependencies, { investigation_id, run_id }) {
  const session = await dependencies.store.getSession(investigation_id);
  const turn = await dependencies.store.getTurn(run_id);
  if (!session || !turn || turn.value.investigation_id !== investigation_id ||
      !session.value.turns?.some((item) => item.id === run_id)) throw new Error("InvestigationNotFound");
  const execution = new Execution(dependencies, { investigation_id, run_id }, session.value, turn.value);
  if (TERMINAL.has(turn.value.status)) {
    await execution.syncSession(turn.value.status);
    return turn.value;
  }
  if (session.value.active_run_id !== run_id) throw new Error("InvestigationNotActive");
  return execution.run();
}
