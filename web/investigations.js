import { setTimeout as wait } from "node:timers/promises";
import { LambdaClient, InvokeCommand } from "@aws-sdk/client-lambda";
import { MemoryInvestigationStore, S3InvestigationStore, InvestigationConflict } from "./investigation-store.js";
import { MemoryStore, S3Store } from "./stores.js";
import { listProcedures, getProcedure, procedureSteps } from "./procedures.js";
import {
  INVESTIGATION_LIMITS, inputHash, scopeFields, investigationError, validateInvestigationId,
  validateInvestigationInput, mutateRecord, isTerminal, publicInvestigation, publicTurn, publicReport,
} from "./investigation-records.js";

export class InvestigationService {
  constructor(settings, dependencies = {}) {
    this.settings = settings;
    this.clock = dependencies.clock || Date.now;
    this.sleep = dependencies.sleep || ((ms, signal) => wait(ms, undefined, { signal }));
    this.store = dependencies.store || (settings.mode === "sample"
      ? new MemoryInvestigationStore(settings) : new S3InvestigationStore(settings));
    this.reportStore = dependencies.reportStore || (settings.mode === "sample"
      ? new MemoryStore(settings) : new S3Store(settings));
    this.enabled = settings.mode === "sample" || (settings.agentBackend === "bma" &&
      Boolean(settings.investigationWorkerArn || dependencies.dispatch));
    this.dispatch = dependencies.dispatch || this.defaultDispatch.bind(this);
    this.client = null;
  }
  now() { return new Date(this.clock()).toISOString(); }
  requireEnabled() {
    if (!this.enabled) throw investigationError("InvestigationsUnavailable", 503);
  }
  catalog() { return { procedures: listProcedures(), enabled: this.enabled }; }

  async defaultDispatch(payload) {
    if (this.settings.mode === "sample") {
      // This in-process path is only for synthetic data; live work is owned by Lambda.
      void import("./investigation-executor.js").then(({ executeInvestigation }) => executeInvestigation({
        settings: this.settings, store: this.store, reportStore: this.reportStore, clock: this.clock,
      }, payload)).catch((error) => {
        console.warn(JSON.stringify({ component: "sample-investigation", code: error.code || error.name }));
      });
      return;
    }
    this.client ||= new LambdaClient({ region: this.settings.appRegion, maxAttempts: 3,
      requestHandler: { connectionTimeout: 3000, requestTimeout: 10000 } });
    const response = await this.client.send(new InvokeCommand({
      FunctionName: this.settings.investigationWorkerArn, InvocationType: "Event",
      Payload: Buffer.from(JSON.stringify(payload)),
    }));
    if (response.StatusCode !== 202) throw investigationError("WorkerDispatchFailed", 503);
  }

  async create(input) {
    this.requireEnabled();
    const body = validateInvestigationInput(input, true);
    let procedure;
    try { procedure = getProcedure(body.procedure_id); }
    catch { throw investigationError("InvalidProcedure", 422); }
    const id = body.request_id, hash = inputHash(body), now = this.now();
    const ref = { id, prompt: body.prompt, language: body.language,
      input_hash: inputHash({ prompt: body.prompt, language: body.language }), status: "queued", created_at: now };
    await this.checkRequestOwner(id, id, ref.input_hash);
    const value = {
      ...scopeFields(this.settings), id, title: body.prompt.slice(0, 120), created_at: now, updated_at: now,
      expires_at: new Date(this.clock() + INVESTIGATION_LIMITS.lifetimeMs).toISOString(),
      status: "queued", procedure: structuredClone(procedure), first_input_hash: hash,
      model: this.settings.model, runtime_arn: this.settings.runtimeArn,
      turns: [ref], active_run_id: id,
    };
    let saved;
    try { saved = await this.store.createSession(value); }
    catch (error) {
      if (error instanceof InvestigationConflict) saved = await this.store.getSession(id);
      else throw error;
    }
    if (!saved || saved.value.first_input_hash !== hash) throw investigationError("RequestIdConflict");
    await this.ensureReservedTurn(saved.value, saved.value.turns[0]);
    await this.kick(id, id);
    return this.get(id, id, false);
  }

  async ensureTurn(session, ref) {
    let saved = await this.store.getTurn(ref.id);
    if (saved) {
      if (saved.value.investigation_id !== session.id || saved.value.input_hash !== ref.input_hash) {
        throw investigationError("RequestIdConflict");
      }
      return saved;
    }
    const turn = {
      ...scopeFields(this.settings), id: ref.id, investigation_id: session.id,
      prompt: ref.prompt, language: ref.language, input_hash: ref.input_hash,
      created_at: ref.created_at, updated_at: ref.created_at,
      deadline_at: new Date(Date.parse(ref.created_at) + this.settings.maxTurnSeconds * 1000).toISOString(),
      status: "queued", phase: "queued", answer: "", evidence: [], errors: [],
      procedure_steps: procedureSteps(session.procedure, [], "queued"), cancel_requested: false,
    };
    try { saved = await this.store.createTurn(turn); }
    catch (error) {
      if (!(error instanceof InvestigationConflict)) throw error;
      saved = await this.store.getTurn(ref.id);
      if (!saved || saved.value.investigation_id !== session.id || saved.value.input_hash !== ref.input_hash) {
        throw investigationError("RequestIdConflict");
      }
    }
    return saved;
  }

  async checkRequestOwner(runId, investigationId, hash) {
    const saved = await this.store.getTurn(runId);
    if (saved && (saved.value.investigation_id !== investigationId || saved.value.input_hash !== hash)) {
      throw investigationError("RequestIdConflict");
    }
    const report = await this.reportStore.get(runId);
    if (report && (report.investigation_id !== investigationId ||
        inputHash({ prompt: report.prompt, language: report.language }) !== hash)) {
      throw investigationError("RequestIdConflict");
    }
  }

  async ensureReservedTurn(session, ref) {
    try { return await this.ensureTurn(session, ref); }
    catch (error) {
      if (error.code === "RequestIdConflict") {
        // Another investigation can win a globally unique UUID between the read
        // and reservation. Release only this still-undispatched reservation.
        await mutateRecord(this.store, "Session", session.id, (current) => {
          if (current.active_run_id !== ref.id) return null;
          const turns = current.turns.filter((item) => item.id !== ref.id);
          return { ...current, turns, active_run_id: null,
            status: turns.at(-1)?.status || "failed", updated_at: this.now() };
        });
      }
      throw error;
    }
  }

  async kick(id, runId) {
    const claimed = await mutateRecord(this.store, "Turn", runId, (turn) => {
      if (turn.investigation_id !== id) throw investigationError("InvestigationNotFound", 404);
      if (isTerminal(turn.status)) return null;
      if (turn.worker_token && Date.parse(turn.lease_until || "") > this.clock()) return null;
      if (turn.last_dispatch_at && this.clock() - Date.parse(turn.last_dispatch_at) < 10000) return null;
      return { ...turn, last_dispatch_at: this.now(), updated_at: this.now() };
    });
    if (!claimed) return;
    try { await this.dispatch({ investigation_id: id, run_id: runId }); }
    catch { throw investigationError("WorkerDispatchFailed", 503); }
  }

  async refreshSession(saved) {
    const session = saved.value;
    if (!session.active_run_id) return saved;
    const ref = session.turns.find((turn) => turn.id === session.active_run_id);
    if (!ref) throw investigationError("InvalidInvestigationRecord", 503);
    const active = await this.ensureTurn(session, ref);
    if (!isTerminal(active.value.status) || active.value.status === "uncertain") return saved;
    return await mutateRecord(this.store, "Session", session.id, (current) => {
      if (current.active_run_id !== active.value.id) return null;
      return { ...current, active_run_id: null, status: active.value.status, updated_at: this.now(),
        turns: current.turns.map((turn) => turn.id === active.value.id ? { ...turn, status: active.value.status } : turn) };
    }) || saved;
  }

  async get(id, runId, reconcile = true) {
    this.requireEnabled(); validateInvestigationId(id);
    if (runId !== undefined) validateInvestigationId(runId);
    let saved = await this.store.getSession(id);
    if (!saved) throw investigationError("InvestigationNotFound", 404);
    saved = await this.refreshSession(saved);
    const selectedId = runId || saved.value.active_run_id || saved.value.turns.at(-1)?.id;
    const ref = saved.value.turns.find((turn) => turn.id === selectedId);
    if (!ref) throw investigationError("InvestigationNotFound", 404);
    let run = await this.ensureTurn(saved.value, ref);
    if (reconcile && !isTerminal(run.value.status)) {
      await this.kick(id, run.value.id);
      run = await this.store.getTurn(run.value.id);
    }
    if (isTerminal(run.value.status)) {
      // The worker can complete between the session and turn reads. Return a
      // consistent terminal view so the next question is immediately available.
      const current = await this.store.getSession(id);
      if (!current) throw investigationError("InvestigationNotFound", 404);
      saved = await this.refreshSession(current);
    }
    return { investigation: publicInvestigation(saved.value, this.settings), run: publicTurn(run.value, this.settings) };
  }

  async list(options = {}) {
    this.requireEnabled();
    return this.store.list(options);
  }

  async submit(id, input) {
    this.requireEnabled(); validateInvestigationId(id);
    const body = validateInvestigationInput(input);
    const hash = inputHash({ prompt: body.prompt, language: body.language });
    const initial = await this.store.getSession(id);
    if (!initial) throw investigationError("InvestigationNotFound", 404);
    await this.refreshSession(initial);
    await this.checkRequestOwner(body.request_id, id, hash);
    const now = this.now();
    const saved = await mutateRecord(this.store, "Session", id, (session) => {
      const existing = session.turns.find((turn) => turn.id === body.request_id);
      if (existing) {
        if (existing.input_hash !== hash) throw investigationError("RequestIdConflict");
        return session;
      }
      if (Date.parse(session.expires_at) <= this.clock()) throw investigationError("InvestigationExpired", 410);
      if (session.active_run_id || session.status === "uncertain") throw investigationError("InvestigationBusy");
      if (session.turns.length >= INVESTIGATION_LIMITS.turns) throw investigationError("InvestigationTurnLimit");
      if (session.model !== this.settings.model || session.runtime_arn !== this.settings.runtimeArn) {
        throw investigationError("InvestigationConfigurationChanged");
      }
      return { ...session, status: "queued", active_run_id: body.request_id, updated_at: now,
        turns: [...session.turns, { id: body.request_id, prompt: body.prompt, language: body.language,
          input_hash: hash, created_at: now, status: "queued" }] };
    });
    const ref = saved.value.turns.find((turn) => turn.id === body.request_id);
    await this.ensureReservedTurn(saved.value, ref);
    await this.kick(id, body.request_id);
    return this.get(id, body.request_id, false);
  }

  async cancel(id, runId) {
    await this.get(id, runId, false);
    await mutateRecord(this.store, "Turn", runId, (turn) => {
      if (turn.investigation_id !== id) throw investigationError("InvestigationNotFound", 404);
      return isTerminal(turn.status) ? null : { ...turn, cancel_requested: true, updated_at: this.now() };
    });
    await this.kick(id, runId);
    return this.get(id, runId, false);
  }

  async *stream(id, runId, { signal } = {}) {
    const deadline = this.clock() + 360000;
    let previous = "", unchanged = 0;
    while (!signal?.aborted && this.clock() < deadline) {
      const state = await this.get(id, runId);
      const current = JSON.stringify(state);
      if (current !== previous) {
        previous = current; unchanged = 0;
        yield { type: "snapshot", ...state };
      } else if (++unchanged % 10 === 0) yield { type: "heartbeat" };
      if (isTerminal(state.run.status)) {
        if (state.run.result) yield { type: "complete", ...publicReport(state.run.result, this.settings) };
        return;
      }
      try { await this.sleep(1000, signal); }
      catch (error) { if (!signal?.aborted) throw error; }
    }
    // Delivery ending is not cancellation. The bounded worker owns the BMA turn.
  }
}
