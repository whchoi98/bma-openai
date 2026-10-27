import assert from "node:assert/strict";
import test from "node:test";
import { InvestigationService } from "../investigations.js";
import { MemoryInvestigationStore } from "../investigation-store.js";
import { MemoryStore } from "../stores.js";

const settings = { mode: "sample", accountId: "000000000000", appRegion: "us-east-1",
  targetRegion: "ap-northeast-2", model: "", agentBackend: "bma", maxTurnSeconds: 300 };
const id = "11111111-2222-4333-8444-555555555555";
const next = "22222222-2222-4333-8444-555555555555";
const other = "33333333-2222-4333-8444-555555555555";
const input = { request_id: id, procedure_id: "inventory", prompt: "서울 EC2 조회", language: "ko" };
function setup() {
  let now = Date.parse("2026-10-27T05:00:00Z");
  const store = new MemoryInvestigationStore(settings), reportStore = new MemoryStore(settings), calls = [];
  const service = new InvestigationService(settings, { store, reportStore, clock: () => now,
    dispatch: async (payload) => { calls.push(payload); }, sleep: async () => {} });
  return { store, reportStore, service, calls, advance: (ms) => { now += ms; } };
}
async function complete(store, runId = id) {
  const turn = await store.getTurn(runId);
  await store.putTurn({ ...turn.value, status: "complete", phase: "complete",
    result: { id: runId, investigation_id: turn.value.investigation_id,
      account_id: settings.accountId, app_region: settings.appRegion, target_region: settings.targetRegion,
      mode: settings.mode, created_at: turn.value.created_at,
      status: "complete", evidence: [], errors: [], answer: "done", report_available: true } }, turn.etag);
}

test("repeated identical creation queues one turn and rejects a changed request with the same id", async () => {
  const { service, calls } = setup();
  const first = await service.create(input);
  const again = await service.create(input);
  assert.equal(first.investigation.id, id);
  assert.equal(again.run.id, id);
  assert.equal(calls.length, 1);
  await assert.rejects(service.create({ ...input, prompt: "different" }), /RequestIdConflict/);
});

test("concurrent follow-ups reserve exactly one active turn", async () => {
  const { service, store, calls } = setup();
  await service.create(input); await complete(store);
  const attempts = await Promise.allSettled([
    service.submit(id, { request_id: next, prompt: "추가 확인", language: "ko" }),
    service.submit(id, { request_id: other, prompt: "다른 확인", language: "ko" }),
  ]);
  assert.equal(attempts.filter((x) => x.status === "fulfilled").length, 1);
  assert.equal(calls.length, 2);
  const current = await store.getSession(id);
  assert.equal(current.value.turns.length, 2);
});

test("GET repairs a reserved turn after a crash before dispatch without adding another question", async () => {
  const { service, store, calls, advance } = setup();
  await service.create(input);
  store.turns.delete(id);
  advance(11000);
  const restored = await service.get(id);
  assert.equal(restored.run.id, id);
  assert.equal(restored.investigation.turns.length, 1);
  assert.equal(calls.length, 2);
});

test("an unexpired worker lease prevents reconnect from dispatching another worker", async () => {
  const { service, store, calls, advance } = setup();
  await service.create(input);
  const run = await store.getTurn(id);
  await store.putTurn({ ...run.value, status: "running", worker_token: "worker",
    lease_until: "2026-10-27T05:03:00.000Z" }, run.etag);
  advance(60000);
  const restored = await service.get(id);
  assert.equal(restored.run.status, "running");
  assert.equal(calls.length, 1);
});

test("stream disconnect stops only delivery and does not request cancellation", async () => {
  const { service, store } = setup();
  await service.create(input);
  const controller = new AbortController();
  const iterator = service.stream(id, id, { signal: controller.signal });
  assert.equal((await iterator.next()).value.type, "snapshot");
  controller.abort();
  await iterator.return();
  assert.equal((await store.getTurn(id)).value.cancel_requested, false);
});

test("cancellation is explicit and foreign turn IDs cannot be accessed", async () => {
  const { service, store } = setup();
  await service.create(input);
  await assert.rejects(service.get(id, other), /InvestigationNotFound/);
  await service.cancel(id, id);
  assert.equal((await store.getTurn(id)).value.cancel_requested, true);
});

test("expired sessions and arbitrary identity fields cannot start a new turn", async () => {
  const { service, store, advance } = setup();
  await assert.rejects(service.create({ ...input, account_id: "999988887777" }), /InvalidInvestigationInput/);
  await service.create(input); await complete(store);
  advance(7 * 60 * 60 * 1000);
  await assert.rejects(service.submit(id, { request_id: next, prompt: "next" }), /InvestigationExpired/);
});

test("a request ID owned by another investigation cannot reserve and block this one", async () => {
  const { service, store } = setup();
  await service.create(input); await complete(store);
  await service.create({ ...input, request_id: other, prompt: "다른 조사" });
  await assert.rejects(service.submit(id, { request_id: other, prompt: "후속 질문" }), /RequestIdConflict/);
  const saved = await store.getSession(id);
  assert.equal(saved.value.active_run_id, null);
  assert.equal(saved.value.turns.length, 1);
});

test("completion between reads returns a terminal investigation without a stale active lock", async () => {
  const { service, store } = setup();
  await service.create(input);
  const read = store.getTurn.bind(store);
  let reads = 0;
  store.getTurn = async (runId) => {
    if (++reads === 2) {
      const saved = await read(runId);
      await store.putTurn({ ...saved.value, status: "complete", phase: "complete" }, saved.etag);
    }
    return read(runId);
  };
  const result = await service.get(id);
  assert.equal(result.run.status, "complete");
  assert.equal(result.investigation.status, "complete");
  assert.equal(result.investigation.active_run_id, null);
});

test("classic report IDs cannot be overwritten by new investigations or follow-up turns", async () => {
  const { service, store, reportStore, calls } = setup();
  const original = {
    id: other, prompt: "기존 단일 조회", language: "ko", status: "failed",
    mode: "sample", account_id: settings.accountId, app_region: settings.appRegion,
    target_region: settings.targetRegion, created_at: "2026-10-27T04:00:00.000Z",
    answer: "saved", evidence: [], errors: [],
  };
  await reportStore.put(original);
  await assert.rejects(service.create({ ...input, request_id: other }), /RequestIdConflict/);
  await service.create(input); await complete(store);
  await assert.rejects(service.submit(id, { request_id: other, prompt: "후속" }), /RequestIdConflict/);
  assert.deepEqual(await reportStore.get(other), original);
  assert.equal(calls.length, 1);
});
