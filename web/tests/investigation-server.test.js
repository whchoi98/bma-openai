import assert from "node:assert/strict";
import { once } from "node:events";
import test from "node:test";
import { createApp } from "../server.js";
import { settingsFromEnv } from "../settings.js";

const id = "11111111-1111-4111-8111-111111111111";
const token = "a".repeat(40);
const live = settingsFromEnv({
  DATA_MODE: "live", EXPECTED_ACCOUNT_ID: "123456789012", BMA_MODEL: "openai.gpt-6-luna",
  BMA_RUNTIME_ARN: "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/example",
  BMA_SESSION_ROLE_ARN: "arn:aws:iam::123456789012:role/BmaSession",
  APP_ACCESS_TOKEN: token, APP_STATE_BUCKET: "sample-state",
});
async function withApp(settings, dependencies, verify) {
  const app = createApp(settings, dependencies);
  app.listen(0, "127.0.0.1");
  await once(app, "listening");
  try { await verify(`http://127.0.0.1:${app.address().port}`); }
  finally { app.closeAllConnections(); await new Promise((resolve) => app.close(resolve)); }
}

test("new HTTP endpoints use top-level authentication and account verification before service access", async () => {
  let identityCalls = 0, serviceCalls = 0;
  await withApp(live, {
    identity: async () => { identityCalls++; return "999988887777"; },
    investigationService: { catalog() { serviceCalls++; return { procedures: [], enabled: true }; } },
  }, async (base) => {
    assert.equal((await fetch(base + "/api/procedures")).status, 401);
    assert.equal(identityCalls, 0);
    const response = await fetch(base + "/api/procedures", { headers: { Authorization: `Bearer ${token}` } });
    assert.equal(response.status, 409);
    assert.deepEqual(await response.json(), { error: "AccountMismatch" });
    assert.equal(identityCalls, 1);
    assert.equal(serviceCalls, 0);
  });
});

test("real sample service supports HTTP creation, previous-turn snapshots and idempotent requests", async () => {
  const dispatches = [];
  await withApp(settingsFromEnv({ DATA_MODE: "sample" }), {
    investigations: { dispatch: async (payload) => { dispatches.push(payload); } },
  }, async (base) => {
    const catalog = await fetch(base + "/api/procedures");
    assert.equal(catalog.status, 200);
    const { procedures, enabled } = await catalog.json();
    assert.equal(enabled, true);
    assert.equal(procedures.length, 4);
    const input = { request_id: id, procedure_id: "inventory", prompt: "Inspect two EC2 instances", language: "en" };
    const send = () => fetch(base + "/api/investigations", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
    });
    const created = await send();
    assert.equal(created.status, 202);
    const body = await created.json();
    assert.equal(body.investigation.id, id);
    assert.equal(body.run.id, id);
    const repeated = await send();
    assert.equal(repeated.status, 202);
    assert.equal((await repeated.json()).run.id, id);
    const historical = await fetch(`${base}/api/investigations/${id}/turns/${id}`);
    assert.equal(historical.status, 200);
    assert.equal((await historical.json()).run.prompt, input.prompt);
    const listing = await (await fetch(base + "/api/investigations?limit=10")).json();
    assert.equal(listing.investigations.length, 1);
    assert.doesNotMatch(JSON.stringify(listing), /000000000000|worker_token|bma_session_id/);
    assert.ok(dispatches.length > 0);
    const oversized = await fetch(base + "/api/investigations", { method: "POST", body: "x".repeat(16_385) });
    assert.equal(oversized.status, 413);
    assert.deepEqual(await oversized.json(), { error: "RequestTooLarge" });
  });
});

test("live Converse and missing-worker installations report a disabled catalog without AWS storage calls", async () => {
  for (const settings of [live, { ...live, agentBackend: "converse", model: "global.openai.gpt-6-luna" }]) {
    await withApp(settings, { identity: async () => "123456789012" }, async (base) => {
      const response = await fetch(base + "/api/procedures", { headers: { Authorization: `Bearer ${token}` } });
      assert.equal(response.status, 200);
      assert.equal((await response.json()).enabled, false);
    });
  }
});

test("sample HTTP worker completes two continuing turns and preserves reused evidence times", async () => {
  await withApp(settingsFromEnv({ DATA_MODE: "sample" }), {}, async (base) => {
    const send = async (path, body) => {
      const response = await fetch(base + path, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      assert.equal(response.status, 202, await response.clone().text());
      return response.json();
    };
    const read = async (runId) => {
      const response = await fetch(`${base}/api/investigations/${id}/turns/${runId}/events`, {
        signal: AbortSignal.timeout(5000),
      });
      assert.equal(response.status, 200);
      const events = (await response.text()).split("\n")
        .filter((line) => line.startsWith("data: ")).map((line) => JSON.parse(line.slice(6)));
      const result = events.find((event) => event.type === "complete");
      assert.ok(result, JSON.stringify(events));
      return result;
    };
    await send("/api/investigations", {
      request_id: id, procedure_id: "inventory", prompt: "서울 EC2와 RDS", language: "ko",
    });
    const first = await read(id);
    const nextId = "22222222-2222-4222-8222-222222222222";
    await send(`/api/investigations/${id}/turns`, {
      request_id: nextId, prompt: "Summarize the previous observations.", language: "en",
    });
    const second = await read(nextId);
    assert.equal(second.evidence_reused, true);
    assert.deepEqual(second.evidence.map((e) => e.observed_at), first.evidence.map((e) => e.observed_at));
    assert.deepEqual(second.source_run_ids, [id]);
    assert.match(second.answer, /Previously observed evidence/);
    const report = await fetch(`${base}/api/runs/${nextId}/report.html`);
    assert.equal(report.status, 200);
    assert.match(await report.text(), /Previously observed evidence/);
  });
});
