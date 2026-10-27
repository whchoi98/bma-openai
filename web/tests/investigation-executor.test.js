import assert from "node:assert/strict";
import test from "node:test";
import { setImmediate as immediate } from "node:timers/promises";
import { executeInvestigation } from "../investigation-executor.js";
import { MemoryInvestigationStore } from "../investigation-store.js";
import { getProcedure } from "../procedures.js";
import samples from "../sample-data.json" with { type: "json" };

const id = (n) => `10000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const settings = { mode: "live", accountId: "123456789012", appRegion: "us-east-1",
  targetRegion: "ap-northeast-2", stateBucket: "executor-test", model: "openai.gpt-6-luna",
  runtimeArn: "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/example",
  sessionRoleArn: "arn:aws:iam::123456789012:role/example", maxTurnSeconds: 300 };
const now = Date.parse("2026-10-27T00:00:00Z");
const marker = (run) => `[aws-ops-turn:${run}]`;
const scope = (s) => ({ account_id: s.accountId, app_region: s.appRegion, target_region: s.targetRegion, mode: s.mode });
const observation = (name, s = settings) => JSON.parse(JSON.stringify(samples[name])
  .replaceAll("000000000000", s.accountId).replaceAll('"mode":"sample"', `"mode":"${s.mode}"`));
const deferred = () => {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
};

async function fixture(options = {}) {
  const s = { ...settings, ...options.settings }, store = new MemoryInvestigationStore(s);
  const session = { ...scope(s), id: id(1), created_at: new Date(now).toISOString(),
    updated_at: new Date(now).toISOString(), expires_at: new Date(now + 6 * 3600_000).toISOString(),
    title: "EC2", status: "queued", active_run_id: id(1), procedure: getProcedure("inventory"),
    turns: [{ id: id(1), prompt: "Inspect EC2", language: "en", status: "queued", created_at: new Date(now).toISOString() }],
    ...options.session };
  const turn = { ...scope(s), id: id(1), investigation_id: id(1), prompt: "Inspect EC2", language: "en",
    input_hash: "fixture", created_at: new Date(now).toISOString(), updated_at: new Date(now).toISOString(),
    deadline_at: new Date(now + 300_000).toISOString(), status: "queued", phase: "queued",
    answer: "", evidence: [], errors: [], procedure_steps: [], cancel_requested: false, ...options.turn };
  await store.createSession(session); await store.createTurn(turn);
  const reports = new Map(), reportStore = {
    async put(record) { reports.set(record.id, structuredClone(record)); },
    async get(run) { return structuredClone(reports.get(run) || null); },
  };
  const bma = fakeBma(s);
  const dependencies = { settings: s, store, reportStore, bmaFactory: () => bma, clock: () => now,
    sleep: async () => { await immediate(); } };
  return { dependencies, store, reports, bma };
}

function fakeBma(s) {
  const sessions = new Map(), items = new Map(), calls = [];
  let counter = 0, turnCounter = 0;
  const bma = {
    sessions, items, calls, afterCreate: null, afterSubmit: null, eventOverride: null, noEvidence: false,
    async createInvestigationSession(instructions, language) {
      calls.push(["create", instructions, language]);
      const sid = `sess_${++counter}`;
      sessions.set(sid, { id: sid, role_arn: s.sessionRoleArn, environment: { runtime_arn: s.runtimeArn },
        agent: { model: s.model, instructions }, status: "idle" });
      items.set(sid, []);
      await bma.afterCreate?.(sid);
      return sid;
    },
    async getSession(sid) { calls.push(["getSession", sid]); return structuredClone(sessions.get(sid)); },
    async listSessions() { calls.push(["listSessions"]); return { data: [...sessions.values()], has_more: false }; },
    async submitInput(sid, text) {
      calls.push(["submit", sid, text]);
      const tid = `turn_${++turnCounter}`;
      const current = [
        { id: `input_${tid}`, type: "message", role: "user", status: "completed", turn_id: tid,
          content: [{ type: "input_text", text }] },
        ...(!bma.noEvidence ? ["get_account_context", "list_ec2_instances"].map((name) => ({
          id: `${tid}_${name}`, type: "mcp_call", server_label: "seoul_aws", name, turn_id: tid,
          status: "completed", output: JSON.stringify(observation(name, s)),
        })) : []),
        { id: `reason_${tid}`, type: "message", role: "assistant", channel: "analysis", turn_id: tid,
          status: "completed", content: [{ type: "output_text", text: "PRIVATE REASONING" }] },
        { id: `answer_${tid}`, type: "message", role: "assistant", channel: "final", turn_id: tid,
          status: "completed", content: [{ type: "output_text", text: `Answer for ${tid}.` }] },
      ];
      items.get(sid).push(...current);
      sessions.get(sid).status = "idle";
      await bma.afterSubmit?.(sid, tid);
      return {};
    },
    async listItems(sid) {
      calls.push(["listItems", sid]);
      const values = structuredClone(items.get(sid));
      return { items: values, complete: true, last_id: values.at(-1)?.id || null };
    },
    async *events(sid) {
      calls.push(["events", sid]);
      if (bma.eventOverride) { yield* bma.eventOverride(sid); return; }
      const current = items.get(sid), tid = current.at(-1)?.turn_id;
      yield { type: "agent.session.turn.reasoning.delta", turn_id: tid, delta: "PRIVATE REASONING" };
      yield { type: "agent.session.turn.output_text.delta", turn_id: tid, delta: "Answer " };
      for (const item of current.filter((item) => item.turn_id === tid)) {
        yield { type: "agent.session.turn.item.done", turn_id: tid, item };
      }
      yield { type: "agent.session.turn.completed", turn_id: tid };
    },
    async cancel(sid) { calls.push(["cancel", sid]); sessions.get(sid).status = "idle"; },
  };
  return bma;
}

const execute = (f, run = id(1)) => executeInvestigation(f.dependencies, { investigation_id: id(1), run_id: run });
const callsOf = (f, kind) => f.bma.calls.filter(([name]) => name === kind);

test("a new investigation creates a scoped session once and persists only public progress", async () => {
  const f = await fixture();
  await execute(f);
  const turn = (await f.store.getTurn(id(1))).value, session = (await f.store.getSession(id(1))).value;
  assert.equal(turn.status, "complete"); assert.equal(turn.result.id, id(1));
  assert.equal(session.active_run_id, null); assert.equal(session.turns[0].status, "complete");
  assert.equal(callsOf(f, "create").length, 1); assert.equal(callsOf(f, "submit").length, 1);
  assert.match(callsOf(f, "create")[0][1], /\[aws-ops-investigation:10000000-/);
  assert.match(callsOf(f, "create")[0][1], /Approved procedure: inventory/);
  assert.ok(callsOf(f, "submit")[0][2].startsWith(marker(id(1))));
  assert.equal(turn.bma_turn_id, "turn_1");
  assert.equal(turn.evidence.length, 2);
  assert.equal(turn.result.procedure_steps.find((step) => step.id === "report").status, "complete");
  assert.doesNotMatch(JSON.stringify(turn), /PRIVATE REASONING|agent\.session\.turn\.reasoning|raw_events/);
  assert.equal(f.reports.get(id(1)).answer, "Procedure: Resource inventory, version 1.0.0.\n\nAnswer for turn_1.");
});

test("valid duplicate workers do not create another BMA request", async () => {
  const f = await fixture(), entered = deferred(), release = deferred();
  f.bma.afterCreate = async () => { entered.resolve(); await release.promise; };
  const first = execute(f);
  await entered.promise;
  await execute(f);
  assert.equal(callsOf(f, "create").length, 1); assert.equal(callsOf(f, "submit").length, 0);
  release.resolve(); await first;
  assert.equal(callsOf(f, "submit").length, 1);
});

test("follow-up turns reuse the BMA session and report prior evidence with its original time", async () => {
  const f = await fixture();
  await execute(f);
  const prior = (await f.store.getTurn(id(1))).value, saved = await f.store.getSession(id(1));
  const created = new Date(now + 1000).toISOString();
  await f.store.createTurn({ ...prior, id: id(2), created_at: created, updated_at: created, status: "queued",
    phase: "queued", prompt: "Summarize that", answer: "", evidence: [], errors: [], result: undefined,
    worker_token: undefined, lease_until: undefined, bma_turn_id: undefined, cancel_requested: false });
  await f.store.putSession({ ...saved.value, active_run_id: id(2), status: "queued",
    turns: [...saved.value.turns, { id: id(2), created_at: created, prompt: "Summarize that", language: "en", status: "queued" }],
  }, saved.etag);
  f.bma.noEvidence = true;
  await execute(f, id(2));
  const current = (await f.store.getTurn(id(2))).value;
  assert.equal(callsOf(f, "create").length, 1); assert.equal(callsOf(f, "submit").length, 2);
  assert.equal(callsOf(f, "submit")[1][1], callsOf(f, "submit")[0][1]);
  assert.equal(current.result.evidence_reused, true);
  assert.deepEqual(current.result.source_run_ids, [id(1)]);
  assert.equal(current.result.evidence[1].observed_at, prior.evidence[1].observed_at);
  assert.doesNotMatch(current.answer, /Answer for turn_1/);
});

test("a create accepted before a transport error is reconciled without another create", async () => {
  const f = await fixture();
  f.bma.afterCreate = () => { throw new Error("accepted but disconnected"); };
  await execute(f);
  assert.equal(callsOf(f, "create").length, 1);
  assert.equal(callsOf(f, "submit").length, 1);
  assert.equal((await f.store.getTurn(id(1))).value.status, "complete");
});

test("an input accepted before a transport error is recovered without resubmission", async () => {
  const f = await fixture();
  f.bma.afterSubmit = () => { throw new Error("accepted but disconnected"); };
  await execute(f);
  assert.equal(callsOf(f, "submit").length, 1);
  assert.equal((await f.store.getTurn(id(1))).value.status, "complete");
});

test("an unavailable reconciliation read leaves ambiguous input blocked as uncertain", async () => {
  const f = await fixture();
  f.bma.afterSubmit = () => { throw new Error("ambiguous input"); };
  f.bma.listItems = async () => { throw new Error("read transport unavailable"); };
  await execute(f);
  assert.equal(callsOf(f, "submit").length, 1);
  assert.equal((await f.store.getTurn(id(1))).value.status, "uncertain");
  assert.equal((await f.store.getSession(id(1))).value.active_run_id, id(1));
});

test("unavailable session reconciliation cannot turn an ambiguous create into another create", async () => {
  const f = await fixture();
  f.bma.afterCreate = () => { throw new Error("ambiguous creation"); };
  f.bma.listSessions = async () => { throw new Error("read transport unavailable"); };
  await execute(f);
  assert.equal(callsOf(f, "create").length, 1);
  assert.equal(callsOf(f, "submit").length, 0);
  assert.equal((await f.store.getTurn(id(1))).value.status, "uncertain");
});

test("a resumed submitting phase never repeats an input when acceptance cannot be proved", async () => {
  const f = await fixture({ session: { bma_session_id: "sess_existing" }, turn: { phase: "submitting", status: "running",
    worker_token: "expired", lease_until: new Date(now - 1000).toISOString() } });
  f.bma.sessions.set("sess_existing", { id: "sess_existing", role_arn: settings.sessionRoleArn,
    environment: { runtime_arn: settings.runtimeArn }, agent: { model: settings.model,
      instructions: `[aws-ops-investigation:${id(1)}]` }, status: "idle" });
  f.bma.items.set("sess_existing", []);
  await execute(f);
  const turn = (await f.store.getTurn(id(1))).value, session = (await f.store.getSession(id(1))).value;
  assert.equal(callsOf(f, "submit").length, 0);
  assert.equal(turn.status, "uncertain"); assert.equal(session.active_run_id, id(1));
});

test("a foreign runtime session is blocked before submitting or cancelling it", async () => {
  const f = await fixture({ session: { bma_session_id: "foreign" } });
  f.bma.sessions.set("foreign", { id: "foreign", role_arn: settings.sessionRoleArn,
    environment: { runtime_arn: settings.runtimeArn.replace("example", "foreign") },
    agent: { model: settings.model, instructions: `[aws-ops-investigation:${id(1)}]` }, status: "idle" });
  await execute(f);
  assert.equal((await f.store.getTurn(id(1))).value.status, "failed");
  assert.equal(callsOf(f, "submit").length, 0); assert.equal(callsOf(f, "cancel").length, 0);
  assert.equal(callsOf(f, "listItems").length, 0);
});

test("an existing session that cannot be verified remains uncertain and blocks new input", async () => {
  const f = await fixture({ session: { bma_session_id: "unavailable" },
    turn: { status: "running", phase: "running" } });
  f.bma.getSession = async () => { throw new Error("transport failure"); };
  await execute(f);
  assert.equal((await f.store.getTurn(id(1))).value.status, "uncertain");
  assert.equal((await f.store.getSession(id(1))).value.active_run_id, id(1));
  assert.equal(callsOf(f, "submit").length, 0);
});

test("queued cancellation completes without creating a BMA session", async () => {
  const f = await fixture({ turn: { cancel_requested: true } });
  await execute(f);
  assert.equal((await f.store.getTurn(id(1))).value.status, "cancelled");
  assert.equal(callsOf(f, "create").length, 0);
  assert.equal((await f.store.getSession(id(1))).value.active_run_id, null);
});

test("cancellation recorded during the turn cancels BMA and releases the active run", async () => {
  const f = await fixture();
  f.bma.afterSubmit = async () => {
    const current = await f.store.getTurn(id(1));
    await f.store.putTurn({ ...current.value, cancel_requested: true }, current.etag);
  };
  await execute(f);
  assert.equal((await f.store.getTurn(id(1))).value.status, "cancelled");
  assert.equal((await f.store.getSession(id(1))).value.active_run_id, null);
  assert.equal(callsOf(f, "cancel").length, 1);
});

test("an expired deadline cancels a verified running BMA session and stops the turn", async () => {
  const f = await fixture();
  let time = now;
  f.dependencies.clock = () => time;
  f.bma.afterSubmit = (sid) => {
    f.bma.sessions.get(sid).status = "in_progress";
    f.bma.items.set(sid, f.bma.items.get(sid).filter((item) => item.role === "user"));
    time = now + 301_000;
  };
  await execute(f);
  const turn = (await f.store.getTurn(id(1))).value;
  assert.equal(turn.status, "failed"); assert.ok(turn.errors.includes("InvestigationDeadlineExceeded"));
  assert.equal(callsOf(f, "cancel").length, 1);
});

test("an unsuccessful cancellation remains uncertain instead of releasing an active BMA turn", async () => {
  const f = await fixture();
  f.bma.afterSubmit = async () => {
    const current = await f.store.getTurn(id(1));
    await f.store.putTurn({ ...current.value, cancel_requested: true }, current.etag);
  };
  f.bma.cancel = async () => { throw new Error("cancel transport failure"); };
  await execute(f);
  const current = (await f.store.getTurn(id(1))).value;
  assert.equal(current.status, "uncertain");
  assert.ok(current.errors.includes("CancelRequestFailed"));
  assert.equal((await f.store.getSession(id(1))).value.active_run_id, id(1));
});

test("cancel acceptance without a terminal session status keeps the investigation blocked", async () => {
  const f = await fixture();
  f.bma.afterSubmit = async (sid) => {
    f.bma.sessions.get(sid).status = "in_progress";
    const current = await f.store.getTurn(id(1));
    await f.store.putTurn({ ...current.value, cancel_requested: true }, current.etag);
  };
  f.bma.cancel = async () => ({ accepted: true });
  await execute(f);
  const current = (await f.store.getTurn(id(1))).value;
  assert.equal(current.status, "uncertain");
  assert.ok(current.errors.includes("CancelStateUncertain"));
  assert.equal((await f.store.getSession(id(1))).value.active_run_id, id(1));
});

test("an already expired recovered run still verifies and cancels its own BMA session", async () => {
  const f = await fixture({ session: { bma_session_id: "sess_expired" },
    turn: { status: "running", phase: "running" } });
  f.dependencies.clock = () => now + 400_000;
  f.bma.sessions.set("sess_expired", { id: "sess_expired", status: "in_progress",
    role_arn: settings.sessionRoleArn, environment: { runtime_arn: settings.runtimeArn },
    agent: { model: settings.model, instructions: `[aws-ops-investigation:${id(1)}]` } });
  await execute(f);
  assert.equal(callsOf(f, "cancel").length, 1);
  assert.equal((await f.store.getTurn(id(1))).value.status, "failed");
  assert.equal((await f.store.getSession(id(1))).value.active_run_id, null);
});

test("scope-invalid evidence is not saved and prevents further model reads", async () => {
  const f = await fixture();
  f.bma.afterSubmit = (sid) => {
    const bad = f.bma.items.get(sid).find((item) => item.name === "list_ec2_instances");
    bad.output = JSON.stringify({ ...observation("list_ec2_instances"), account_id: "999988887777" });
  };
  await execute(f);
  const turn = (await f.store.getTurn(id(1))).value;
  assert.equal(turn.status, "failed");
  assert.doesNotMatch(JSON.stringify(turn.evidence), /999988887777/);
  assert.equal(callsOf(f, "cancel").length, 1);
  const cancelledAt = f.bma.calls.findIndex(([name]) => name === "cancel");
  assert.equal(f.bma.calls.slice(cancelledAt + 1).filter(([name]) => ["listItems", "submit", "create"].includes(name)).length, 0);
});

test("polling recovers a completed turn when the event stream disconnects", async () => {
  const f = await fixture();
  f.bma.eventOverride = async function* () { throw new Error("stream unavailable"); };
  await execute(f);
  const turn = (await f.store.getTurn(id(1))).value;
  assert.equal(turn.status, "complete"); assert.equal(turn.answer, "Procedure: Resource inventory, version 1.0.0.\n\nAnswer for turn_1.");
  assert.equal(callsOf(f, "submit").length, 1);
});

test("phase-only analysis items cannot enter answers or persisted reports", async () => {
  const f = await fixture();
  f.bma.afterSubmit = (sid, tid) => f.bma.items.get(sid).push({
    id: "hidden-phase", type: "message", role: "assistant", phase: "analysis", turn_id: tid, status: "completed",
    content: [{ type: "output_text", text: "PRIVATE PHASE REASONING" }],
  });
  await execute(f);
  assert.doesNotMatch(JSON.stringify((await f.store.getTurn(id(1))).value), /PRIVATE/);
  assert.doesNotMatch(JSON.stringify(f.reports.get(id(1))), /PRIVATE/);
});

test("lease heartbeats continue while session creation is waiting", async () => {
  const f = await fixture(), entered = deferred(), release = deferred();
  let time = now;
  f.dependencies.clock = () => time;
  f.bma.afterCreate = async () => { entered.resolve(); await release.promise; };
  const running = execute(f);
  await entered.promise;
  const initial = (await f.store.getTurn(id(1))).value.lease_until;
  time += 20_000;
  for (let attempt = 0; attempt < 30 && (await f.store.getTurn(id(1))).value.lease_until === initial; attempt++) await immediate();
  const refreshed = (await f.store.getTurn(id(1))).value;
  assert.ok(Date.parse(refreshed.lease_until) >= time + 40_000);
  release.resolve(); await running;
});

test("a worker that loses its lease does not finalize or cancel the replacement worker", async () => {
  const f = await fixture();
  f.bma.afterSubmit = async () => {
    const saved = await f.store.getTurn(id(1));
    await f.store.putTurn({ ...saved.value, worker_token: "replacement", lease_until: new Date(now + 45_000).toISOString() }, saved.etag);
  };
  await execute(f);
  assert.equal((await f.store.getTurn(id(1))).value.worker_token, "replacement");
  assert.equal((await f.store.getTurn(id(1))).value.result, undefined);
  assert.equal(callsOf(f, "cancel").length, 0);
});

test("a failed BMA read after lease replacement cannot cancel or finalize the replacement", async () => {
  const f = await fixture();
  f.dependencies.sleep = () => new Promise(() => {});
  f.bma.listItems = async () => {
    const current = await f.store.getTurn(id(1));
    await f.store.putTurn({ ...current.value, worker_token: "replacement",
      lease_until: new Date(now + 45_000).toISOString() }, current.etag);
    throw new Error("BMA read transport failure after takeover");
  };
  const result = await execute(f);
  assert.equal(result.status, "duplicate");
  assert.equal(callsOf(f, "cancel").length, 0);
  assert.equal((await f.store.getTurn(id(1))).value.worker_token, "replacement");
  assert.equal((await f.store.getTurn(id(1))).value.result, undefined);
  assert.equal((await f.store.getSession(id(1))).value.active_run_id, id(1));
});

test("cancellation renews an expired owned lease before a competing worker can take over", async () => {
  const f = await fixture(), entered = deferred(), release = deferred();
  let time = now;
  f.dependencies.clock = () => time;
  f.dependencies.sleep = () => new Promise(() => {});
  f.bma.listItems = async () => {
    time = now + 46_000;
    throw new Error("BMA read transport failure after lease expiry");
  };
  const originalCancel = f.bma.cancel.bind(f.bma);
  f.bma.cancel = async (sid) => {
    entered.resolve();
    await release.promise;
    return originalCancel(sid);
  };
  const first = execute(f);
  await entered.promise;
  const cancelling = (await f.store.getTurn(id(1))).value;
  assert.ok(Date.parse(cancelling.lease_until) >= time + 45_000);
  const competitor = await execute(f);
  assert.equal(competitor.status, "duplicate");
  assert.equal((await f.store.getTurn(id(1))).value.worker_token, cancelling.worker_token);
  release.resolve();
  await first;
  assert.equal(callsOf(f, "cancel").length, 1);
});

test("BMA creates and submits only after the respective durable checkpoint", async () => {
  const f = await fixture();
  f.bma.afterCreate = async () => {
    assert.equal((await f.store.getTurn(id(1))).value.phase, "creating_session");
  };
  f.bma.afterSubmit = async (sid) => {
    assert.equal((await f.store.getTurn(id(1))).value.phase, "submitting");
    assert.equal((await f.store.getSession(id(1))).value.bma_session_id, sid);
  };
  await execute(f);
});

test("a committed session index failure is visible without duplicating BMA work", async () => {
  const f = await fixture(), original = f.store.putSession.bind(f.store);
  let failed = false;
  f.store.putSession = async (value, etag) => {
    const saved = await original(value, etag);
    if (!failed && value.bma_session_id) {
      failed = true;
      throw Object.assign(new Error("InvestigationIndexWriteFailed"), {
        code: "InvestigationIndexWriteFailed", recordSaved: true, ...saved,
      });
    }
    return saved;
  };
  await execute(f);
  assert.equal(callsOf(f, "create").length, 1); assert.equal(callsOf(f, "submit").length, 1);
  assert.ok((await f.store.getTurn(id(1))).value.errors.includes("InvestigationIndexWriteFailed"));
});

test("a final session index failure remains visible on the completed turn", async () => {
  const f = await fixture(), original = f.store.putSession.bind(f.store);
  f.store.putSession = async (value, etag) => {
    const saved = await original(value, etag);
    if (value.active_run_id === null) throw Object.assign(new Error("InvestigationIndexWriteFailed"), {
      code: "InvestigationIndexWriteFailed", recordSaved: true, ...saved,
    });
    return saved;
  };
  const result = await execute(f);
  assert.ok(result.errors.includes("InvestigationIndexWriteFailed"));
  assert.ok((await f.store.getTurn(id(1))).value.errors.includes("InvestigationIndexWriteFailed"));
  assert.equal((await f.store.getSession(id(1))).value.active_run_id, null);
});

test("report storage failure can resume finalization after deadline without another BMA request", async () => {
  const f = await fixture();
  const failure = new Error("report transport failure"), original = f.dependencies.reportStore.put;
  f.dependencies.reportStore.put = async () => { throw failure; };
  await assert.rejects(execute(f), (error) => error === failure);
  const incomplete = (await f.store.getTurn(id(1))).value;
  assert.equal(incomplete.phase, "finalizing"); assert.equal(incomplete.final_status, "complete");
  f.dependencies.reportStore.put = original;
  f.dependencies.clock = () => now + 400_000;
  const callsBefore = f.bma.calls.length;
  await execute(f);
  assert.equal(f.bma.calls.length, callsBefore);
  assert.equal((await f.store.getTurn(id(1))).value.status, "complete");
  assert.equal((await f.store.getSession(id(1))).value.active_run_id, null);
});

test("a colliding report ID is preserved while the investigation retains its final snapshot", async () => {
  for (const conflicting of [
    { id: id(1), prompt: "classic question", language: "en" },
    { id: id(1), investigation_id: id(9), prompt: "Inspect EC2", language: "en" },
    { id: id(1), investigation_id: id(1), prompt: "different input", language: "en" },
    { id: id(1), investigation_id: id(1), prompt: "Inspect EC2", language: "ko" },
  ]) {
    const f = await fixture(), previous = { ...scope(settings), ...conflicting, answer: "Unrelated saved report" };
    f.reports.set(id(1), previous);
    await execute(f);
    const current = (await f.store.getTurn(id(1))).value;
    assert.equal(current.status, "failed");
    assert.ok(current.errors.includes("ReportIdConflict"));
    assert.equal(current.result.report_available, false);
    assert.match(current.result.answer, /Answer for turn_1/);
    assert.deepEqual(f.reports.get(id(1)), previous);
  }
});

test("an existing report belonging to the identical investigation request may be finalized", async () => {
  const f = await fixture();
  f.reports.set(id(1), { ...scope(settings), id: id(1), investigation_id: id(1), prompt: "Inspect EC2",
    language: "en", answer: "Earlier same-request snapshot" });
  await execute(f);
  assert.equal((await f.store.getTurn(id(1))).value.status, "complete");
  assert.match(f.reports.get(id(1)).answer, /Answer for turn_1/);
});

test("an in-progress MCP item waits for its completed output before finalizing", async () => {
  const f = await fixture(), original = f.bma.listItems.bind(f.bma);
  let reads = 0;
  f.bma.afterSubmit = (sid, tid) => {
    f.bma.items.get(sid).push({ id: "pending-tool", type: "mcp_call", server_label: "seoul_aws",
      name: "list_rds_instances", status: "in_progress", turn_id: tid });
  };
  f.bma.listItems = async (sid) => {
    reads++;
    if (reads === 3) {
      assert.equal(f.reports.size, 0, "an unresolved tool must prevent report completion");
      const pending = f.bma.items.get(sid).find((item) => item.id === "pending-tool");
      pending.status = "completed";
      pending.output = JSON.stringify(observation("list_rds_instances"));
    }
    return original(sid);
  };
  await execute(f);
  const current = (await f.store.getTurn(id(1))).value;
  assert.equal(current.status, "complete");
  assert.ok(reads >= 3);
  assert.ok(current.evidence.some((item) => item.tool === "list_rds_instances"));
  assert.ok(!current.errors.includes("InvalidToolResult"));
  assert.equal(callsOf(f, "cancel").length, 0);
});

test("recovered streams preserve snapshots and never append replayed delta prefixes", async () => {
  const f = await fixture({ session: { bma_session_id: "sess_recovered" }, turn: {
    status: "running", phase: "running", answer: "Hello world", bma_turn_id: "turn_recovered",
    lease_until: new Date(now - 1000).toISOString(), worker_token: "old",
  } });
  f.bma.sessions.set("sess_recovered", { id: "sess_recovered", status: "in_progress", role_arn: settings.sessionRoleArn,
    environment: { runtime_arn: settings.runtimeArn }, agent: { model: settings.model,
      instructions: `[aws-ops-investigation:${id(1)}]` } });
  const input = { id: "input", type: "message", role: "user", status: "completed", turn_id: "turn_recovered",
    content: [{ type: "input_text", text: marker(id(1)) + "\nQuestion" }] };
  f.bma.items.set("sess_recovered", [input]);
  let time = now;
  f.dependencies.clock = () => time;
  const snapshots = [], originalPut = f.store.putTurn.bind(f.store);
  f.store.putTurn = async (value, etag) => {
    if (value.phase === "running" && value.answer) snapshots.push({ time, answer: value.answer });
    return originalPut(value, etag);
  };
  f.bma.eventOverride = async function* () {
    for (const delta of ["Hello ", "world", " again"]) {
      time += 1100;
      yield { type: "agent.session.turn.output_text.delta", turn_id: "turn_recovered", delta };
      await immediate();
    }
    f.bma.items.get("sess_recovered").push(
      { id: "context", type: "mcp_call", server_label: "seoul_aws", name: "get_account_context",
        turn_id: "turn_recovered", status: "completed", output: JSON.stringify(observation("get_account_context")) },
      { id: "resource", type: "mcp_call", server_label: "seoul_aws", name: "list_ec2_instances",
        turn_id: "turn_recovered", status: "completed", output: JSON.stringify(observation("list_ec2_instances")) },
      { id: "final", type: "message", role: "assistant", phase: "final_answer", status: "completed",
        turn_id: "turn_recovered", content: [{ type: "output_text", text: "Hello world again" }] });
    f.bma.sessions.get("sess_recovered").status = "idle";
  };
  await execute(f);
  assert.equal(callsOf(f, "submit").length, 0);
  assert.ok(snapshots.every((item) => ["Hello world", "Hello world again"].includes(item.answer)));
  assert.match((await f.store.getTurn(id(1))).value.answer, /Hello world again$/);
  assert.doesNotMatch((await f.store.getTurn(id(1))).value.answer, /Hello worldHello/);
});

test("public progress checkpoints are written at most once per second while deltas arrive", async () => {
  const f = await fixture();
  let time = now;
  f.dependencies.clock = () => time;
  f.bma.afterSubmit = (sid) => {
    f.bma.items.set(sid, f.bma.items.get(sid).filter((item) => item.role === "user"));
    f.bma.sessions.get(sid).status = "in_progress";
  };
  const checkpoints = [], originalPut = f.store.putTurn.bind(f.store);
  f.store.putTurn = async (value, etag) => {
    if (value.phase === "running" && value.answer) checkpoints.push({ time, answer: value.answer });
    return originalPut(value, etag);
  };
  f.bma.eventOverride = async function* (sid) {
    for (const delta of ["one ", "two ", "three ", "four ", "five ", "six"]) {
      time += 400;
      yield { type: "agent.session.turn.output_text.delta", turn_id: "turn_1", delta };
      await immediate();
    }
    f.bma.items.get(sid).push(
      { id: "tool", type: "mcp_call", server_label: "seoul_aws", name: "list_ec2_instances",
        turn_id: "turn_1", status: "completed", output: JSON.stringify(observation("list_ec2_instances")) },
      { id: "answer", type: "message", role: "assistant", status: "completed", turn_id: "turn_1",
        content: [{ type: "output_text", text: "one two three four five six" }] });
    f.bma.sessions.get(sid).status = "idle";
  };
  await execute(f);
  assert.ok(checkpoints.length >= 1);
  for (let i = 1; i < checkpoints.length; i++) assert.ok(checkpoints[i].time - checkpoints[i - 1].time >= 1000);
  assert.ok(checkpoints.every((item) => !item.answer.includes("PRIVATE")));
});

test("sample investigations run without constructing a BMA client", async () => {
  const f = await fixture({ settings: { mode: "sample", accountId: "000000000000", model: "" } });
  f.dependencies.bmaFactory = () => assert.fail("sample mode called BMA");
  await execute(f);
  const turn = (await f.store.getTurn(id(1))).value;
  assert.equal(turn.status, "complete"); assert.equal(turn.evidence[0].mode, "sample");
  assert.ok(turn.evidence.some((item) => item.tool === "list_ec2_instances"));
});

test("a terminal retry repairs session metadata without executing BMA again", async () => {
  const f = await fixture();
  await execute(f);
  const saved = await f.store.getSession(id(1));
  await f.store.putSession({ ...saved.value, active_run_id: id(1), status: "running",
    turns: saved.value.turns.map((turn) => ({ ...turn, status: "running" })) }, saved.etag);
  const before = f.bma.calls.length;
  await execute(f);
  assert.equal(f.bma.calls.length, before);
  assert.equal((await f.store.getSession(id(1))).value.active_run_id, null);
});
