import assert from "node:assert/strict";
import { once } from "node:events";
import test from "node:test";
import { createApp } from "../server.js";
import { settingsFromEnv } from "../settings.js";
import { publicItems } from "../evidence.js";
import { BmaClient, BmaError, parseSSE, sessionPayload } from "../bma.js";
import { renderHtml, renderMarkdown } from "../reports.js";
import { LiveRunner } from "../runners.js";
import samples from "../sample-data.json" with { type: "json" };

const sample = () => settingsFromEnv({ DATA_MODE: "sample" });
const live = () => settingsFromEnv({
  DATA_MODE: "live", EXPECTED_ACCOUNT_ID: "111122223333", APP_REGION: "us-east-1", TARGET_REGION: "ap-northeast-2",
  BMA_MODEL: "openai.test-model", BMA_RUNTIME_ARN: "arn:aws:bedrock-agentcore:us-east-1:111122223333:runtime/demo-1234567890",
  BMA_SESSION_ROLE_ARN: "arn:aws:iam::111122223333:role/BmaSession", APP_ACCESS_TOKEN: "x".repeat(40), APP_STATE_BUCKET: "demo-state",
});

async function withApp(config, callback, dependencies = {}) {
  const server = createApp(config, dependencies);
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const base = `http://127.0.0.1:${server.address().port}`;
  try { await callback(base); }
  finally { server.closeAllConnections(); await new Promise((resolve) => server.close(resolve)); }
}

const eventsOf = (text) => text.split("\n").filter((line) => line.startsWith("data: ")).map((line) => JSON.parse(line.slice(6)));

test("Node Web Function serves sample inventory, evidence and both report formats", async () => {
  await withApp(sample(), async (base) => {
    const context = await (await fetch(base + "/api/context")).json();
    assert.equal(context.account_id, "000000000000");
    assert.equal(context.target_region, "ap-northeast-2");
    const response = await fetch(base + "/api/chat", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ prompt: "서울 리전 EC2와 RDS 현황을 알려줘" }) });
    assert.equal(response.status, 200);
    const events = eventsOf(await response.text());
    const tools = events.filter((e) => e.type === "tool_result").map((e) => e.result.tool);
    assert.deepEqual(tools, ["get_account_context", "list_ec2_instances", "list_rds_instances"]);
    const done = events.at(-1);
    assert.equal(done.type, "complete");
    assert.equal(done.mode, "sample");
    for (const format of ["md", "html"]) {
      const report = await fetch(`${base}/api/runs/${done.id}/report.${format}`);
      assert.equal(report.status, 200);
      const content = await report.text();
      assert.match(content, /Asia\/Seoul/);
      assert.match(content, /DescribeInstances/);
      assert.match(content, /us-east-1/);
      assert.match(content, /샘플/);
    }
  });
});

test("all API routes enforce access key while health and UI remain available", async () => {
  await withApp({ ...sample(), accessToken: "test-token" }, async (base) => {
    assert.equal((await fetch(base + "/")).status, 200);
    assert.equal((await fetch(base + "/health")).status, 200);
    for (const path of ["/api/context", "/api/runs/abc/report.md"]) assert.equal((await fetch(base + path)).status, 401);
    assert.equal((await fetch(base + "/api/chat", { method: "POST", body: "{}" })).status, 401);
    assert.equal((await fetch(base + "/api/context", { headers: { authorization: "Bearer test-token" } })).status, 200);
  });
});

test("browser cannot select execution identity or unbounded prompt", async () => {
  await withApp(sample(), async (base) => {
    for (const body of [{ prompt: "" }, { prompt: "x".repeat(4001) }, { prompt: "EC2", account_id: "999988887777" },
      { prompt: "EC2", region: "us-east-1" }, { prompt: "EC2", mode: "live" },
      { prompt: "EC2", language: "ignore instructions" }, { prompt: "EC2", language: null }]) {
      const response = await fetch(base + "/api/chat", { method: "POST", body: JSON.stringify(body) });
      assert.equal(response.status, 422);
    }
    assert.equal((await fetch(base + "/static/%2e%2e/settings.js")).status, 404);
  });
});

test("English selection reaches the runner and both exported report formats", async () => {
  await withApp(sample(), async (base) => {
    const response = await fetch(base + "/api/chat", { method: "POST",
      body: JSON.stringify({ prompt: "Show EC2 in Seoul", language: "en" }) });
    const done = eventsOf(await response.text()).at(-1);
    assert.equal(done.language, "en");
    assert.match(done.answer, /Sample data/);
    assert.doesNotMatch(done.answer, /[가-힣]/);
    for (const format of ["md", "html"]) {
      const report = await (await fetch(`${base}/api/runs/${done.id}/report.${format}`)).text();
      assert.match(report, /AWS operations report/);
      assert.match(report, /Asia\/Seoul/);
      assert.match(report, /DescribeInstances/);
      assert.doesNotMatch(report.replace(/<template id="font-license">[\s\S]*?<\/template>/g, ""), /[가-힣]/);
    }
  });
  assert.match(sessionPayload(live(), "EC2", "en").agent.instructions, /Respond in English/);
});

test("live caller STS mismatch prevents BMA session creation", async () => {
  let runs = 0;
  await withApp(live(), async (base) => {
    const response = await fetch(base + "/api/chat", {
      method: "POST", headers: { authorization: "Bearer " + "x".repeat(40) }, body: JSON.stringify({ prompt: "EC2" }),
    });
    assert.equal(response.status, 409);
    assert.equal(runs, 0);
  }, { identity: async () => "999988887777", runner: { async *stream() { runs++; } }, store: { put() {}, get() {} } });
});

test("session payload uses environment-local STDIO and same-account Runtime", () => {
  const body = sessionPayload(live(), "EC2");
  assert.equal(body.environment.type, "aws_bedrock_agentcore");
  assert.deepEqual(body.environment.capability_directories, ["/opt/bma/skills"]);
  const tool = body.agent.tools[0];
  assert.equal(tool.transport.type, "stdio");
  assert.ok(tool.transport.env_vars.includes("TARGET_REGION"));
  assert.ok(tool.transport.env_vars.includes("EXPECTED_ACCOUNT_ID"));
  assert.ok(tool.transport.env_vars.includes("MAX_RESOURCES"));
  assert.equal(tool.required, true);
  assert.equal(tool.allowed_tools.length, 24);
  assert.equal(tool.transport.env, undefined);
  assert.throws(() => settingsFromEnv({ ...process.env, DATA_MODE: "live", EXPECTED_ACCOUNT_ID: "111122223333",
    BMA_RUNTIME_ARN: "arn:aws:bedrock-agentcore:ap-northeast-2:111122223333:runtime/x" }));
});

test("BMA HTTP is signed in us-east-1 and ambiguous POST is not retried", async () => {
  const requests = [];
  const client = new BmaClient(live(), { credentials: { accessKeyId: "testing", secretAccessKey: "testing" },
    fetchImpl: async (url, options) => {
      requests.push({ url, options });
      return new Response("private upstream text", { status: 503 });
    } });
  await assert.rejects(client.createSession("EC2"), /BmaHTTP503/);
  assert.equal(requests.length, 1);
  assert.match(requests[0].options.headers.authorization, /us-east-1\/bedrock-mantle\/aws4_request/);
  assert.match(requests[0].url, /^https:\/\/bedrock-mantle.us-east-1.api.aws/);
});

test("internal reasoning, shell output and analysis messages never become public output", () => {
  const result = publicItems([
    { id: "r", type: "reasoning", summary: "SECRET" },
    { id: "c", type: "command_execution", output: "SECRET" },
    { id: "a", type: "message", role: "assistant", channel: "analysis", content: [{ type: "output_text", text: "SECRET" }] },
    { id: "m", type: "message", role: "assistant", content: [{ type: "output_text", text: "관측 답변" }] },
  ], live());
  assert.equal(result.answer, "관측 답변");
  assert.doesNotMatch(JSON.stringify(result), /SECRET/);
});

test("events use the documented stream=true query parameter", async () => {
  const client = new BmaClient(live(), {
    credentials: { accessKeyId: "testing", secretAccessKey: "testing" },
    fetchImpl: async (url, options) => {
      assert.equal(new URL(url).searchParams.get("stream"), "true");
      assert.equal(options.headers.accept, "text/event-stream");
      return new Response('data: {"type":"agent.session.turn.completed"}\n\n');
    },
  });
  const events = [];
  for await (const event of client.events("session_1")) events.push(event);
  assert.equal(events.at(-1).type, "agent.session.turn.completed");
});

test("transient event stream startup failures are retried without duplicating a session", async () => {
  let calls = 0;
  const delays = [];
  const client = new BmaClient(live(), {
    credentials: { accessKeyId: "testing", secretAccessKey: "testing" },
    sleep: async (ms) => { delays.push(ms); },
    fetchImpl: async (url, options) => {
      assert.equal(options.method, "GET");
      calls++;
      if (calls < 3) return new Response("not ready", { status: 503 });
      return new Response('data: {"type":"agent.session.turn.completed"}\n\n');
    },
  });
  const events = [];
  for await (const event of client.events("session_1")) events.push(event);
  assert.equal(calls, 3);
  assert.deepEqual(delays, [5000, 10000]);
  assert.equal(events.at(-1).type, "agent.session.turn.completed");
});

test("BMA session creation streams from the POST response without a second event connection", async () => {
  const requests = [];
  const client = new BmaClient(live(), {
    credentials: { accessKeyId: "testing", secretAccessKey: "testing" },
    fetchImpl: async (url, options) => {
      requests.push({ url, options });
      assert.equal(options.method, "POST");
      assert.equal(JSON.parse(options.body).stream, true);
      assert.equal(options.headers.accept, "text/event-stream");
      return new Response([
        'data: {"type":"agent.session.created","session":{"id":"session_stream"}}\n\n',
        'data: {"type":"agent.session.turn.output_text.delta","delta":"서울"}\n\n',
        'data: {"type":"agent.session.turn.completed"}\n\n',
      ].join(""));
    },
  });
  const events = [];
  for await (const event of client.createSessionEvents("서울 조회")) events.push(event);
  assert.equal(requests.length, 1);
  assert.equal(events[0].session.id, "session_stream");
  assert.equal(events[1].delta, "서울");
});

test("visible text deltas reach the client before completion while reasoning stays private", async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  let reconciled = false;
  const data = structuredClone(samples.list_ec2_instances);
  Object.assign(data, { mode: "live", account_id: "111122223333" });
  const evidence = { id: "ec2", type: "mcp_call", server_label: "seoul_aws", name: "list_ec2_instances", output: JSON.stringify(data) };
  const message = { id: "answer", type: "message", role: "assistant",
    content: [{ type: "output_text", text: "## 서울 EC2\n\n확인한 결과입니다." }] };
  const client = {
    async *createSessionEvents() {
      yield { type: "agent.session.created", session: { id: "session_stream" } };
      yield { type: "agent.session.turn.reasoning.delta", delta: "PRIVATE REASONING" };
      yield { type: "agent.session.turn.item.done", item: evidence };
      yield { type: "agent.session.turn.output_text.delta", delta: "## 서울 EC2\n\n" };
      await gate;
      yield { type: "agent.session.turn.output_text.delta", delta: "확인한 결과입니다." };
      yield { type: "agent.session.turn.item.done", item: message };
      yield { type: "agent.session.turn.completed" };
    },
    async listItems() { reconciled = true; return { items: [evidence, message], complete: true }; },
    async cancel() {},
  };
  const iterator = new LiveRunner(live(), () => client).stream("서울 조회");
  const events = [];
  while (true) {
    const next = await iterator.next();
    assert.equal(next.done, false);
    events.push(next.value);
    if (next.value.type === "answer_delta") break;
  }
  assert.equal(reconciled, false);
  assert.equal(events.at(-1).delta, "## 서울 EC2\n\n");
  release();
  for await (const event of iterator) events.push(event);
  assert.equal(events.at(-1).type, "result");
  assert.equal(events.at(-1).answer, message.content[0].text);
  assert.doesNotMatch(JSON.stringify(events), /PRIVATE REASONING/);
});

test("identity failure cancels before reconciliation and stops consuming more tool results", async () => {
  const order = [];
  const failed = structuredClone(samples.get_account_context);
  Object.assign(failed, { mode: "live", account_id: null, status: "api_error", data: [],
    errors: [{ service: "sts", api: "GetCallerIdentity", code: "ExpiredToken", kind: "api_error" }] });
  failed.api_calls[0].success = false;
  const failure = { id: "failed", type: "mcp_call", server_label: "seoul_aws", name: "get_account_context", output: JSON.stringify(failed) };
  const fake = {
    async createSession() { return "session_1"; },
    async *events() {
      yield { type: "agent.session.turn.item.done", item: failure };
      order.push("consumed-after-failure");
      yield { type: "agent.session.turn.completed" };
    },
    async cancel() { order.push("cancel"); },
    async listItems() { order.push("items"); return { items: [failure], complete: true }; },
  };
  const runner = new LiveRunner(live(), () => fake);
  const events = [];
  for await (const event of runner.stream("EC2")) events.push(event);
  assert.deepEqual(order, ["cancel", "items"]);
  assert.match(events.at(-1).answer, /계정.*검증|STS/);
  assert.notEqual(events.at(-1).status, "complete");
});

test("fragmented UTF-8 and multiline SSE frames are preserved", async () => {
  const bytes = new TextEncoder().encode(': keep-alive\r\n\r\nevent: complete\r\ndata: {"text":"서울",\r\ndata: "type":"complete"}\r\n\r\n');
  const response = new Response(new ReadableStream({
    start(controller) { for (let i = 0; i < bytes.length; i += 3) controller.enqueue(bytes.slice(i, i + 3)); controller.close(); },
  }));
  const values = [];
  for await (const value of parseSSE(response)) values.push(value);
  assert.deepEqual(values.at(-1), { text: "서울", type: "complete" });
});

test("successful streamed evidence survives failed durable reconciliation", async () => {
  const output = structuredClone(samples.list_ec2_instances);
  Object.assign(output, { mode: "live", account_id: "111122223333" });
  const item = { id: "ec2", type: "mcp_call", server_label: "seoul_aws", name: "list_ec2_instances", output: JSON.stringify(output) };
  const fake = {
    async createSession() { return "session_1"; },
    async *events() { yield { type: "agent.session.turn.item.done", item }; yield { type: "agent.session.turn.completed" }; },
    async listItems() { throw new BmaError("BmaHTTP503"); },
    async cancel() { assert.fail("Completed turn should not be cancelled."); },
  };
  const values = [];
  for await (const value of new LiveRunner(live(), () => fake).stream("EC2")) values.push(value);
  assert.equal(values.at(-1).evidence[0].count, 2);
  assert.equal(values.at(-1).status, "partial");
  assert.ok(values.at(-1).errors.includes("BmaHTTP503"));
});

test("browser disconnect cancels the running BMA turn", async () => {
  let resolveCancel;
  const cancelled = new Promise((resolve) => { resolveCancel = resolve; });
  const runner = new LiveRunner(live(), ({ signal }) => ({
    async createSession() { return "session_1"; },
    async *events() {
      if (!signal.aborted) await new Promise((resolve) => signal.addEventListener("abort", resolve, { once: true }));
      throw new BmaError("EventStreamDisconnected");
    },
    async listItems() { assert.fail("Disconnected browser must not start reconciliation."); },
    async cancel() { resolveCancel(); },
  }));
  await withApp(live(), async (base) => {
    const response = await fetch(base + "/api/chat", { method: "POST",
      headers: { authorization: "Bearer " + "x".repeat(40) }, body: JSON.stringify({ prompt: "EC2" }) });
    const reader = response.body.getReader();
    await reader.read();
    await reader.cancel();
    await Promise.race([cancelled, new Promise((_, reject) => setTimeout(() => reject(new Error("No cancellation")), 1500))]);
  }, { identity: async () => "111122223333", runner, store: { async put() {}, async get() {} } });
});

test("HTML report escapes active content and records missing metrics", () => {
  const record = { id: "test", mode: "sample", created_at: "2026-10-26T00:00:00Z",
    prompt: "<script>bad()</script>", answer: "<img src=x onerror=bad()>",
    evidence: [samples["get_resource_metrics:sample-idle"]], errors: [] };
  const output = renderHtml(record);
  assert.doesNotMatch(output, /<script>|<img/);
  assert.match(output, /&lt;script&gt;/);
  assert.match(output, /데이터 없음/);
  assert.match(renderMarkdown(record), /2026-10-26 09:00:00 KST/);
  assert.match(renderMarkdown(record), /이번 조회 서비스: cloudwatch, lambda/);
});

test("HTML report renders Markdown and redacts preview content without changing stored evidence", () => {
  const record = { id: "test", language: "en", mode: "sample", created_at: "2026-10-26T00:00:00Z",
    prompt: "View report", answer: "## Resource summary\n\nAccount: 0000**0000**0000\n\n| Resource | State |\n| --- | --- |\n| EC2 | running |\n\n<script>bad()</script>",
    evidence: [structuredClone(samples.get_account_context)], errors: [] };
  const original = structuredClone(record);
  const preview = renderHtml(record, { preview: true, redact: true, theme: "dark" });
  assert.match(preview, /<h2>Resource summary<\/h2>/);
  assert.match(preview, /<table>/);
  assert.match(preview, /\*{9}000/);
  assert.doesNotMatch(preview, /000000000000|<script|<style>/);
  assert.match(preview, /data-theme="dark"/);
  assert.match(preview, /href="\/static\/report.css"/);
  assert.doesNotMatch(preview, /[가-힣]/);
  assert.deepEqual(record, original);
  const download = renderHtml(record, { redact: true });
  assert.match(download, /<h2>Resource summary<\/h2>/);
  assert.match(download, /<style>/);
  assert.match(download, /<template id="font-license">/);
});

test("report preview requires authentication and accepts only defined presentation options", async () => {
  const id = "11111111-1111-4111-8111-111111111111";
  const record = { id, language: "ko", mode: "sample", created_at: "2026-10-26T00:00:00Z",
    prompt: "보고서", answer: "## 조회 결과\n\n확인했습니다.", evidence: [samples.get_account_context], errors: [] };
  await withApp({ ...sample(), accessToken: "test-token" }, async (base) => {
    const path = `/api/runs/${id}/report.html`;
    assert.equal((await fetch(base + path + "?view=preview")).status, 401);
    const headers = { authorization: "Bearer test-token" };
    const preview = await fetch(base + path + "?view=preview&theme=dark", { headers });
    assert.equal(preview.status, 200);
    assert.match(preview.headers.get("content-disposition"), /^inline/);
    assert.match(await preview.text(), /href="\/static\/report.css"/);
    const download = await fetch(base + path + "?view=download", { headers });
    assert.match(download.headers.get("content-disposition"), /^attachment/);
    assert.equal((await fetch(base + path + "?view=unexpected", { headers })).status, 400);
    assert.equal((await fetch(base + path + "?view=preview&theme=invalid", { headers })).status, 400);
  }, { store: { async get() { return record; } } });
});

test("a failed report without tool evidence still masks the deployment account", async () => {
  const id = "22222222-2222-4222-8222-222222222222";
  const config = live();
  const record = { id, language: "en", mode: "live", created_at: "2026-10-26T00:00:00Z",
    prompt: `Check EC2 in account ${config.accountId}`, answer: `Account: ${config.accountId}`,
    evidence: [], errors: ["NoResourceEvidence"] };
  await withApp(config, async (base) => {
    for (const view of ["preview", "download"]) {
      const response = await fetch(`${base}/api/runs/${id}/report.html?view=${view}`, {
        headers: { authorization: "Bearer " + config.accessToken },
      });
      assert.equal(response.status, 200);
      const html = await response.text();
      assert.doesNotMatch(html, new RegExp(config.accountId));
      assert.match(html, /\*{9}333/);
    }
    for (const format of ["md", "html"]) {
      const response = await fetch(`${base}/api/runs/${id}/report.${format}`, {
        headers: { authorization: "Bearer " + config.accessToken },
      });
      assert.equal(response.status, 200);
      const report = await response.text();
      assert.doesNotMatch(report, new RegExp(config.accountId));
      assert.match(report, /\*{9}333/);
    }
  }, { identity: async () => config.accountId, store: { async get() { return record; } } });
});

test("history loads a saved scoped result and exports Office files without another model call", async () => {
  let calls = 0;
  const runner = { async *stream() {
    calls++;
    yield { type: "result", answer: "## Saved result\n\nAccount: 000000000000",
      evidence: [samples.get_account_context, samples.list_ec2_instances], errors: [], status: "complete" };
  } };
  await withApp(sample(), async (base) => {
    const response = await fetch(base + "/api/chat", { method: "POST",
      body: JSON.stringify({ prompt: "EC2", language: "en" }) });
    const saved = eventsOf(await response.text()).at(-1);
    const page = await (await fetch(base + "/api/runs?limit=1")).json();
    assert.equal(page.runs.length, 1);
    assert.equal(page.runs[0].id, saved.id);
    assert.equal(page.runs[0].account_id, "*********000");
    const loaded = await (await fetch(`${base}/api/runs/${saved.id}`)).json();
    assert.deepEqual(loaded.evidence, saved.evidence);
    assert.equal(calls, 1);
    for (const format of ["docx", "pptx"]) {
      const file = await fetch(`${base}/api/runs/${saved.id}/report.${format}`);
      assert.equal(file.status, 200);
      assert.match(file.headers.get("content-type"), /openxmlformats/);
      assert.equal(Buffer.from(await file.arrayBuffer()).subarray(0, 2).toString(), "PK");
    }
    assert.equal(calls, 1);
    assert.equal((await fetch(base + "/api/runs?account_id=999988887777")).status, 400);
    assert.equal((await fetch(base + "/api/runs?limit=21")).status, 400);
  }, { runner });
});

test("a history index failure preserves an already saved report", async () => {
  await withApp(sample(), async (base) => {
    const response = await fetch(base + "/api/chat", { method: "POST",
      body: JSON.stringify({ prompt: "EC2" }) });
    const saved = eventsOf(await response.text()).at(-1);
    assert.equal(saved.report_available, true);
    assert.equal(saved.status, "partial");
    assert.ok(saved.errors.includes("HistoryIndexWriteFailed"));
  }, { store: { async put() { throw Object.assign(new Error("HistoryIndexWriteFailed"), { recordSaved: true }); } } });
});
