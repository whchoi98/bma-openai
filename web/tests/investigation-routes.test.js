import assert from "node:assert/strict";
import { once } from "node:events";
import { PassThrough } from "node:stream";
import test from "node:test";
import { createInvestigationRoutes } from "../investigation-routes.js";

const id = "11111111-1111-4111-8111-111111111111";
const runId = "22222222-2222-4222-8222-222222222222";
const input = { request_id: id, procedure_id: "inventory", prompt: "Inspect EC2", language: "en" };
const envelope = { investigation: { id }, run: { id: runId } };

function response() {
  const res = new PassThrough();
  res.headersSent = false;
  res.statusCode = 200;
  res.headers = {};
  res.setHeader = (key, value) => { res.headers[key] = value; };
  res.writeHead = (status, headers = {}) => {
    res.statusCode = status;
    res.headers = { ...res.headers, ...headers };
    res.headersSent = true;
  };
  const chunks = [];
  res.on("data", (chunk) => chunks.push(chunk));
  res.text = () => Buffer.concat(chunks).toString();
  return res;
}
function service(overrides = {}) {
  return {
    catalog: async () => ({ procedures: [], enabled: true }),
    create: async () => envelope,
    list: async () => ({ investigations: [], complete: true, next_cursor: null }),
    get: async () => envelope, submit: async () => envelope,
    cancel: async () => envelope,
    async *stream() { yield { type: "snapshot", ...envelope }; yield { type: "complete", id: runId }; },
    ...overrides,
  };
}
function harness(dependencies = {}) {
  let verifications = 0;
  const route = createInvestigationRoutes({
    service: service(), verifyAccount: async () => { verifications++; return "123456789012"; },
    json(res, status, body) {
      res.writeHead(status, { "content-type": "application/json" });
      res.end(JSON.stringify(body));
    },
    responseHeaders: { "cache-control": "no-store" },
    ...dependencies,
  });
  return {
    get verifications() { return verifications; },
    async call(path, { method = "GET", body, rawBody, res = response() } = {}) {
      const req = new PassThrough();
      req.method = method;
      req.headers = { "content-type": "application/json" };
      const running = route(req, res, new URL(path, "http://localhost"));
      req.end(rawBody ?? (body === undefined ? "" : JSON.stringify(body)));
      const handled = await running;
      return { res, handled, text: res.text(), body: res.text() ? JSON.parse(res.text()) : null };
    },
    route,
  };
}

test("all investigation endpoints verify account before invoking their service operation", async () => {
  const seen = [];
  let checked = 0;
  const operations = service({
    catalog() { seen.push(["catalog", checked]); return { enabled: true, procedures: [] }; },
    create(value) { seen.push(["create", checked, value]); return envelope; },
    list(value) { seen.push(["list", checked, value]); return { investigations: [] }; },
    get(...args) { seen.push(["get", checked, ...args]); return envelope; },
    submit(...args) { seen.push(["submit", checked, ...args]); return envelope; },
    cancel(...args) { seen.push(["cancel", checked, ...args]); return envelope; },
  });
  const app = harness({ service: operations, verifyAccount: async () => { checked++; } });
  const calls = [
    ["/api/procedures", {}, 200],
    ["/api/investigations", { method: "POST", body: input }, 202],
    ["/api/investigations?limit=2&cursor=YWJj", {}, 200],
    [`/api/investigations/${id}`, {}, 200],
    [`/api/investigations/${id}/turns/${runId}`, {}, 200],
    [`/api/investigations/${id}/turns`, { method: "POST", body: {
      request_id: runId, prompt: "Follow up", language: "ko",
    } }, 202],
    [`/api/investigations/${id}/turns/${runId}/cancel`, { method: "POST", body: {} }, 202],
  ];
  for (const [path, options, status] of calls) {
    const result = await app.call(path, options);
    assert.equal(result.res.statusCode, status);
    assert.equal(result.handled, true);
  }
  assert.deepEqual(seen.map((operation) => operation[1]), [1, 2, 3, 4, 5, 6, 7]);
  assert.deepEqual(seen[1][2], input);
  assert.deepEqual(seen[2][2], { limit: 2, cursor: "YWJj" });
  assert.deepEqual(seen[4].slice(2), [id, runId]);
  assert.deepEqual(seen[6].slice(2), [id, runId]);
});

test("strict methods, route shapes, queries, identifiers and request schemas reject before service calls", async () => {
  let creates = 0;
  const app = harness({ service: service({ create() { creates++; return envelope; } }) });
  const invalid = [
    ["/api/procedures", { method: "POST", body: {} }, 405],
    ["/api/procedures?region=us-east-1", {}, 400],
    ["/api/investigations?limit=1&limit=2", {}, 400],
    ["/api/investigations?limit=21", {}, 400],
    ["/api/investigations?limit=2.5", {}, 400],
    ["/api/investigations?cursor=" + "a".repeat(4097), {}, 400],
    [`/api/investigations/${id}/unknown`, {}, 404],
    ["/api/investigations/not-a-uuid", {}, 422],
    ["/api/investigations", { method: "POST", body: { ...input, account_id: "999988887777" } }, 422],
    ["/api/investigations", { method: "POST", body: { ...input, prompt: "" } }, 422],
    ["/api/investigations", { method: "POST", body: { ...input, language: "xx" } }, 422],
    ["/api/investigations", { method: "POST", rawBody: "{" }, 400],
    ["/api/investigations", { method: "POST", rawBody: "x".repeat(16_385) }, 413],
    [`/api/investigations/${id}/turns/${runId}/cancel`, { method: "POST", body: { force: true } }, 422],
  ];
  for (const [path, options, status] of invalid) {
    const result = await app.call(path, options);
    assert.equal(result.res.statusCode, status, path);
  }
  assert.equal(creates, 0);
  assert.equal(app.verifications, invalid.length);
  assert.equal((await app.call("/api/chat")).handled, false);
});

test("account failure and unknown service errors expose only safe error codes", async () => {
  let creates = 0;
  const blocked = harness({ service: service({ create() { creates++; } }),
    verifyAccount: async () => { throw Object.assign(new Error("AccountMismatch"), { httpStatus: 409 }); } });
  const denied = await blocked.call("/api/investigations", { method: "POST", body: input });
  assert.equal(denied.res.statusCode, 409);
  assert.deepEqual(denied.body, { error: "AccountMismatch" });
  assert.equal(creates, 0);
  const privateError = harness({ service: service({ list() {
    throw Object.assign(new Error("secret key and private session"), { code: "PrivateSession-123456789012", httpStatus: 418 });
  } }) });
  const failed = await privateError.call("/api/investigations");
  assert.equal(failed.res.statusCode, 503);
  assert.deepEqual(failed.body, { error: "InvestigationUnavailable" });
});

test("SSE disconnect aborts only its local subscription and never cancels the investigation", async () => {
  let subscribedSignal, cancelCalls = 0, verified = 0;
  let ready;
  const subscribed = new Promise((resolve) => { ready = resolve; });
  const app = harness({ verifyAccount: async () => { verified++; }, service: service({
    cancel() { cancelCalls++; },
    async *stream(actualId, actualRun, { signal }) {
      assert.equal(actualId, id);
      assert.equal(actualRun, runId);
      assert.equal(verified, 1);
      subscribedSignal = signal;
      yield { type: "snapshot", ...envelope };
      ready();
      if (!signal.aborted) await once(signal, "abort");
    },
  }) });
  const req = new PassThrough(), res = response();
  req.method = "GET";
  const running = app.route(req, res, new URL(`/api/investigations/${id}/turns/${runId}/events`, "http://localhost"));
  req.end();
  await subscribed;
  assert.match(res.text(), /^data: {"type":"snapshot"/);
  res.destroy();
  await running;
  assert.equal(subscribedSignal.aborted, true);
  assert.equal(cancelCalls, 0);
  assert.match(res.headers["content-type"], /^text\/event-stream/);
  assert.equal(res.headers["cache-control"], "no-store");
});

test("an SSE failure after the first snapshot emits a safe error rather than a fake completion", async () => {
  const app = harness({ service: service({
    async *stream() {
      yield { type: "snapshot", ...envelope };
      throw new Error("S3 path with 123456789012 and credentials");
    },
  }) });
  const req = new PassThrough(), res = response();
  req.method = "GET";
  const running = app.route(req, res, new URL(`/api/investigations/${id}/turns/${runId}/events`, "http://localhost"));
  req.end();
  await running;
  assert.match(res.text(), /"type":"error","code":"InvestigationUnavailable"/);
  assert.doesNotMatch(res.text(), /123456789012|credentials|"type":"complete"/);
});
