import assert from "node:assert/strict";
import test from "node:test";
import { ConverseRunner, inferenceCredentials } from "../converse.js";
import samples from "../sample-data.json" with { type: "json" };

const settings = {
  mode: "live", accountId: "111122223333", appRegion: "us-east-1", targetRegion: "ap-northeast-2",
  model: "global.openai.gpt-6-luna", maxTurnSeconds: 300,
  runtimeArn: "arn:aws:bedrock-agentcore:us-east-1:111122223333:runtime/demo-123",
  sessionRoleArn: "arn:aws:iam::111122223333:role/inference",
};
function result(name) {
  const value = structuredClone(samples[name]);
  value.account_id = settings.accountId;
  value.mode = "live";
  return { structuredContent: value };
}

test("ConverseStream text is forwarded immediately and tool use executes only through MCP", async () => {
  const requests = [], called = [];
  let round = 0;
  const client = {
    async send(command) {
      requests.push(command.input);
      round++;
      return { stream: (async function* () {
        if (round === 1) {
          yield { contentBlockDelta: { contentBlockIndex: 0, delta: { reasoningContent: { text: "PRIVATE" } } } };
          yield { contentBlockStart: { contentBlockIndex: 1, start: { toolUse: { toolUseId: "lookup", name: "list_ec2_instances" } } } };
          yield { contentBlockDelta: { contentBlockIndex: 1, delta: { toolUse: { input: "{}" } } } };
          yield { messageStop: { stopReason: "tool_use" } };
        } else {
          yield { contentBlockDelta: { contentBlockIndex: 0, delta: { text: "## 서울 EC2\n" } } };
          yield { contentBlockDelta: { contentBlockIndex: 0, delta: { text: "확인한 리소스 2개입니다." } } };
          yield { messageStop: { stopReason: "end_turn" } };
        }
      })() };
    },
  };
  const mcp = {
    async listTools() { return [{ name: "get_account_context", inputSchema: { type: "object", properties: {} } },
      { name: "list_ec2_instances", inputSchema: { type: "object", properties: {} } }]; },
    async callTool(name) { called.push(name); return result(name); },
  };
  const events = [];
  for await (const event of new ConverseRunner(settings, { client, mcp }).stream("서울 EC2 조회")) events.push(event);
  assert.deepEqual(called, ["get_account_context", "list_ec2_instances"]);
  assert.equal(requests[0].modelId, "global.openai.gpt-6-luna");
  assert.ok(events.findIndex((e) => e.type === "answer_delta") < events.findIndex((e) => e.type === "result"));
  assert.equal(events.at(-1).answer, "## 서울 EC2\n확인한 리소스 2개입니다.");
  assert.equal(events.at(-1).evidence.length, 2);
  assert.doesNotMatch(JSON.stringify(events), /PRIVATE/);
  assert.ok(requests[0].system.some((block) => block.text.includes("aws-resource-inventory")));
});

test("account mismatch stops before global model inference", async () => {
  let inference = false;
  const mismatch = result("get_account_context");
  Object.assign(mismatch.structuredContent, { account_id: "999988887777", status: "account_mismatch", data: [] });
  const runner = new ConverseRunner(settings, {
    client: { async send() { inference = true; throw new Error("should not infer"); } },
    mcp: { async listTools() { return []; }, async callTool() { return mismatch; } },
  });
  const events = [];
  for await (const event of runner.stream("조회")) events.push(event);
  assert.equal(inference, false);
  assert.equal(events.at(-1).status, "failed");
  assert.match(events.at(-1).answer, /계정/);
});

test("selected English overrides Skill language without changing the Luna model", async () => {
  let request;
  const runner = new ConverseRunner(settings, {
    client: { async send(command) {
      request = command.input;
      return { stream: (async function* () {
        yield { contentBlockDelta: { contentBlockIndex: 0, delta: { text: "No resources were queried." } } };
        yield { messageStop: { stopReason: "end_turn" } };
      })() };
    } },
    mcp: { async listTools() { return []; }, async callTool(name) { return result(name); } },
  });
  for await (const _ of runner.stream("Check resources", { language: "en" })) { /* consume */ }
  assert.equal(request.modelId, "global.openai.gpt-6-luna");
  assert.match(request.system.at(-1).text, /Respond in English/);
  assert.match(request.system.at(-1).text, /without em dashes, middle dots/);
});

test("a failed stream preserves the visible partial answer and marks it incomplete", async () => {
  let round = 0;
  const runner = new ConverseRunner(settings, {
    client: {
      async send() {
        const current = ++round;
        return { stream: (async function* () {
          if (current === 1) {
            yield { contentBlockStart: { contentBlockIndex: 0, start: { toolUse: { toolUseId: "ec2", name: "list_ec2_instances" } } } };
            yield { contentBlockDelta: { contentBlockIndex: 0, delta: { toolUse: { input: "{}" } } } };
            yield { messageStop: { stopReason: "tool_use" } };
          } else {
            yield { contentBlockDelta: { contentBlockIndex: 0, delta: { text: "## 확인한 EC2\n부분 분석입니다." } } };
            throw new Error("private upstream diagnostic");
          }
        })() };
      },
    },
    mcp: { async listTools() { return []; }, async callTool(name) { return result(name); } },
  });
  const events = [];
  for await (const event of runner.stream("서울 EC2 조회")) events.push(event);
  assert.equal(events.at(-1).answer, "## 확인한 EC2\n부분 분석입니다.");
  assert.equal(events.at(-1).status, "partial");
  assert.deepEqual(events.at(-1).errors, ["ConverseStreamFailed"]);
  assert.doesNotMatch(JSON.stringify(events), /private upstream/);
});

test("opaque reasoning fragments are joined for tool continuation and never exposed", async () => {
  const requests = [];
  const runner = new ConverseRunner(settings, {
    client: {
      async send(command) {
        requests.push(structuredClone(command.input));
        const first = requests.length === 1;
        return { stream: (async function* () {
          if (first) {
            for (const bytes of [[1, 2], [3, 4]]) {
              yield { contentBlockDelta: { contentBlockIndex: 0, delta: { reasoningContent: { redactedContent: Uint8Array.from(bytes) } } } };
            }
            yield { contentBlockStart: { contentBlockIndex: 1, start: { toolUse: { toolUseId: "ec2", name: "list_ec2_instances" } } } };
            yield { contentBlockDelta: { contentBlockIndex: 1, delta: { toolUse: { input: "{}" } } } };
            yield { messageStop: { stopReason: "tool_use" } };
          } else {
            yield { contentBlockDelta: { contentBlockIndex: 0, delta: { text: "조회했습니다." } } };
            yield { messageStop: { stopReason: "end_turn" } };
          }
        })() };
      },
    },
    mcp: { async listTools() { return []; }, async callTool(name) { return result(name); } },
  });
  const events = [];
  for await (const event of runner.stream("서울 EC2 조회")) events.push(event);
  const reasoning = requests[1].messages[3].content[0].reasoningContent.redactedContent;
  assert.deepEqual([...reasoning], [1, 2, 3, 4]);
  assert.doesNotMatch(JSON.stringify(events), /reasoningContent|redactedContent/);
});

test("credential acquisition stops on the turn abort even while the provider is stalled", async () => {
  const controller = new AbortController();
  let forwarded;
  const credentials = inferenceCredentials(settings, controller.signal, {
    async send(command, options) {
      forwarded = options.abortSignal;
      assert.equal(command.input.RoleArn, settings.sessionRoleArn);
      return new Promise(() => {});
    },
    destroy() {},
  });
  const pending = credentials();
  controller.abort();
  await assert.rejects(pending, { name: "AbortError" });
  assert.equal(forwarded, controller.signal);
});
