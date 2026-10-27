import assert from "node:assert/strict";
import test from "node:test";
import { createInvestigationController, canContinueInvestigation, investigationStepState } from "../ui/investigations.js";

const firstId = "11111111-1111-4111-8111-111111111111";
const secondId = "22222222-2222-4222-8222-222222222222";
const thirdId = "33333333-3333-4333-8333-333333333333";
const procedure = {
  id: "inventory", version: "1.0.0", sha256: "abc",
  name: { ko: "리소스 인벤토리", en: "Resource inventory" },
  description: { ko: "리소스를 확인합니다.", en: "Inspect resources." },
  steps: [{ id: "account", label: { ko: "계정 확인", en: "Verify account" }, tools: ["get_caller_identity"] }],
};
function snapshot(overrides = {}) {
  const run = {
    id: firstId, investigation_id: firstId, status: "running", phase: "running",
    prompt: "Inspect EC2", language: "en", created_at: "2026-10-27T00:00:00Z",
    updated_at: "2026-10-27T00:00:01Z", answer: "", evidence: [], errors: [],
    procedure_steps: [{ ...procedure.steps[0], status: "pending" }], result: null,
    ...overrides,
  };
  return { investigation: {
    id: firstId, title: "Inspect EC2", status: run.status, procedure,
    created_at: run.created_at, updated_at: run.updated_at,
    turns: [{ id: run.id, prompt: run.prompt, language: run.language, status: run.status, created_at: run.created_at }],
    active_run_id: ["queued", "running"].includes(run.status) ? run.id : null,
    expires_at: "2099-10-27T06:00:00Z",
  }, run };
}
const json = (body, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" },
});
function eventStream(events) {
  return new Response(new ReadableStream({
    start(controller) {
      for (const event of events) controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\r\n\r\n`));
      controller.close();
    },
  }), { headers: { "Content-Type": "text/event-stream" } });
}
function memoryStorage(initial = null) {
  const values = new Map(initial ? [["aws-desk-last-investigation", initial]] : []);
  return { values, getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key) };
}
async function settled(predicate) {
  for (let n = 0; n < 50; n++) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 2));
  }
  assert.fail("The investigation state did not settle");
}
function makeController(fetchImpl, options = {}) {
  return createInvestigationController({
    fetchImpl, headers: () => ({ Authorization: "Bearer memory-only-key" }),
    storage: memoryStorage(), randomUUID: () => firstId, ...options,
  });
}

test("repeated snapshots replace answer and evidence and retain the final report", async () => {
  const evidence = { tool: "list_ec2", observed_at: "2026-10-27T00:00:01Z" };
  const finalRecord = { id: firstId, status: "complete", answer: "Complete answer",
    evidence: [evidence], report_available: true };
  const partial = snapshot({ answer: "Partial answer", evidence: [evidence] });
  const complete = snapshot({ status: "complete", answer: finalRecord.answer, evidence: [evidence], result: finalRecord });
  const rendered = [], reports = [], requests = [];
  const controller = makeController(async (url, options) => {
    requests.push({ url, options });
    if (url.endsWith("/events")) return eventStream([
      { type: "snapshot", ...partial }, { type: "snapshot", ...partial },
      { type: "snapshot", ...complete }, { type: "complete", ...finalRecord },
    ]);
    return json(snapshot({ status: "queued" }), 202);
  }, { onSnapshot: ({ run }) => rendered.push(run), onComplete: (record) => reports.push(record) });
  await controller.submit({ procedureId: "inventory", prompt: "Inspect EC2", language: "en" });
  await settled(() => controller.getState().connection === "complete");
  assert.equal(controller.getState().run.answer, "Complete answer");
  assert.equal(controller.getState().run.evidence.length, 1);
  assert.equal(rendered.filter((run) => run.answer === "Partial answer").length, 2);
  assert.ok(rendered.every((run) => run.evidence.length <= 1));
  assert.equal(reports.at(-1).report_available, true);
  assert.equal(requests[1].options.headers.Authorization, "Bearer memory-only-key");
  assert.equal(requests[1].options.method, "GET");
});

test("connect restores the last investigation using GET without resubmitting a turn", async () => {
  const storage = memoryStorage(firstId), calls = [];
  const done = snapshot({ status: "complete" });
  const controller = makeController(async (url, options) => {
    calls.push([url, options.method]);
    if (url === "/api/procedures") return json({ enabled: true, procedures: [procedure] });
    if (url === "/api/investigations?limit=10") return json({ investigations: [done.investigation], next_cursor: null, complete: true });
    return json(done);
  }, { storage });
  await controller.connect();
  assert.equal(controller.getState().investigation.id, firstId);
  assert.ok(calls.every(([, method]) => method === "GET"));
  assert.ok(calls.some(([url]) => url === `/api/investigations/${firstId}`));
  assert.deepEqual([...storage.values], [["aws-desk-last-investigation", firstId]]);
});

test("a disconnected stream remains unfinished and reconnect uses the same GET stream", async () => {
  const calls = [];
  const controller = makeController(async (url, options) => {
    calls.push([url, options.method]);
    if (url.endsWith("/events")) return eventStream([{ type: "snapshot", ...snapshot({ answer: "Saved progress" }) }]);
    return json(snapshot());
  });
  await controller.open(firstId);
  await settled(() => controller.getState().connection === "disconnected");
  assert.equal(controller.getState().run.status, "running");
  assert.equal(controller.getState().run.answer, "Saved progress");
  await controller.reconnect();
  await settled(() => controller.getState().connection === "disconnected");
  assert.equal(calls.filter(([url]) => url.endsWith("/events")).length, 2);
  assert.ok(calls.every(([, method]) => method === "GET"));
});

test("double submission and explicit retry preserve the original UUID and request", async () => {
  let release, attempts = 0, uuidCalls = 0;
  const bodies = [];
  const controller = makeController(async (url, options) => {
    bodies.push(JSON.parse(options.body));
    attempts++;
    if (attempts === 1) {
      await new Promise((resolve) => { release = resolve; });
      throw new TypeError("Network request failed");
    }
    return json(snapshot({ status: "complete" }), 202);
  }, { randomUUID: () => { uuidCalls++; return firstId; } });
  const first = controller.submit({ procedureId: "inventory", prompt: "Inspect EC2", language: "en" });
  const duplicate = controller.submit({ procedureId: "inventory", prompt: "Inspect EC2", language: "en" });
  release();
  await Promise.all([first, duplicate]);
  assert.equal(attempts, 1);
  assert.equal(controller.getState().canRetry, true);
  await controller.retry();
  assert.equal(attempts, 2);
  assert.equal(uuidCalls, 1);
  assert.deepEqual(bodies[1], { request_id: firstId, procedure_id: "inventory", prompt: "Inspect EC2", language: "en" });
});

test("follow-up requests stay in the investigation and older turns use their snapshot endpoint", async () => {
  const calls = [];
  const initial = snapshot({ status: "complete" });
  const next = snapshot({ id: secondId, status: "complete", prompt: "Summarize the findings" });
  next.investigation.turns.unshift(initial.investigation.turns[0]);
  const controller = makeController(async (url, options) => {
    calls.push({ url, options });
    if (options.method === "POST") return json(next, 202);
    if (url.includes("/turns/")) return json(initial);
    return json(initial);
  }, { randomUUID: () => secondId });
  await controller.open(firstId);
  await controller.submit({ prompt: "Summarize the findings", language: "en" });
  assert.equal(calls[1].url, `/api/investigations/${firstId}/turns`);
  assert.deepEqual(JSON.parse(calls[1].options.body), { request_id: secondId, prompt: "Summarize the findings", language: "en" });
  await controller.openTurn(firstId);
  assert.equal(calls.at(-1).url, `/api/investigations/${firstId}/turns/${firstId}`);
  assert.equal(controller.getState().run.prompt, "Inspect EC2");
});

test("cancel targets only the active turn and does not fabricate terminal status", async () => {
  const calls = [];
  const controller = makeController(async (url, options) => {
    calls.push({ url, options });
    if (url.endsWith("/cancel")) return json({ accepted: true }, 202);
    if (url.endsWith("/events")) return eventStream([]);
    return json(snapshot());
  });
  await controller.open(firstId);
  await controller.cancel();
  const request = calls.find(({ url }) => url.endsWith("/cancel"));
  assert.equal(request.url, `/api/investigations/${firstId}/turns/${firstId}/cancel`);
  assert.equal(request.options.body, "{}");
  assert.equal(controller.getState().run.status, "running");
});

test("active, uncertain, expired and ten-turn investigations cannot accept a follow-up", () => {
  const base = snapshot({ status: "complete" }).investigation;
  assert.equal(canContinueInvestigation(base), true);
  assert.equal(canContinueInvestigation({ ...base, active_run_id: secondId }), false);
  assert.equal(canContinueInvestigation({ ...base, status: "uncertain" }), false);
  assert.equal(canContinueInvestigation({ ...base, expires_at: "2000-01-01T00:00:00Z" }), false);
  assert.equal(canContinueInvestigation({ ...base, turns: Array(10).fill(base.turns[0]) }), false);
  assert.equal(investigationStepState("mystery"), "pending");
  assert.equal(investigationStepState("not_requested"), "not_requested");
});

test("late responses from a previous investigation cannot overwrite the current selection", async () => {
  let release;
  const later = snapshot({ id: thirdId, investigation_id: thirdId, status: "complete" });
  later.investigation.id = thirdId;
  const controller = makeController(async (url) => {
    if (url.endsWith(firstId)) return new Promise((resolve) => { release = () => resolve(json(snapshot())); });
    return json(later);
  });
  const earlier = controller.open(firstId);
  await controller.open(thirdId);
  release();
  await earlier;
  assert.equal(controller.getState().investigation.id, thirdId);
});

test("recovery of an accepted request clears retry state and permits the next question", async () => {
  let posts = 0;
  const controller = makeController(async (url, options) => {
    if (options.method === "POST") {
      posts++;
      if (posts === 1) throw new TypeError("Response lost after acceptance");
      return json(snapshot({ id: secondId, status: "complete" }), 202);
    }
    return json(snapshot({ status: "complete" }));
  }, { randomUUID: () => posts ? secondId : firstId });
  await controller.submit({ procedureId: "inventory", prompt: "Inspect EC2", language: "en" });
  assert.equal(controller.getState().canRetry, true);
  await controller.reconnect();
  assert.equal(controller.getState().canRetry, false);
  await controller.submit({ prompt: "Summarize", language: "en" });
  assert.equal(posts, 2);
});

test("an SSE error after a snapshot does not enable a final report or mark completion", async () => {
  const completed = [];
  const controller = makeController(async (url) => url.endsWith("/events")
    ? eventStream([{ type: "snapshot", ...snapshot({ answer: "Progress" }) },
      { type: "error", code: "InvestigationReadFailed" }])
    : json(snapshot()), { onComplete: (record) => completed.push(record) });
  await controller.open(firstId);
  await settled(() => controller.getState().connection === "disconnected");
  assert.equal(controller.getState().run.status, "running");
  assert.equal(controller.getState().error, "InvestigationReadFailed");
  assert.deepEqual(completed, []);
});

test("late connection responses cannot reopen an investigation after disconnect", async () => {
  let release;
  const controller = makeController(async (url) => {
    if (url === "/api/procedures") return new Promise((resolve) => {
      release = () => resolve(json({ enabled: true, procedures: [procedure] }));
    });
    if (url.includes("?")) return json({ investigations: [], next_cursor: null });
    return json(snapshot({ status: "complete" }));
  }, { storage: memoryStorage(firstId) });
  const connection = controller.connect();
  controller.disconnect();
  release();
  await connection;
  assert.equal(controller.getState().investigation, null);
  assert.equal(controller.getState().connected, false);
});

test("a rejected editable question can be corrected without retrying the rejected payload", async () => {
  let count = 0;
  const controller = makeController(async () => {
    count++;
    if (count === 1) return json({ error: "UnsupportedInvestigationRequest" }, 400);
    return json(snapshot({ id: secondId, status: "complete" }), 202);
  }, { randomUUID: () => count ? secondId : firstId });
  await controller.submit({ procedureId: "inventory", prompt: "Unsupported question", language: "en" });
  assert.equal(controller.getState().error, "UnsupportedInvestigationRequest");
  assert.equal(controller.getState().canRetry, false);
  await controller.submit({ procedureId: "inventory", prompt: "Inspect EC2", language: "en" });
  assert.equal(controller.getState().run.id, secondId);
});
