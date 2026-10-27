import assert from "node:assert/strict";
import test from "node:test";
import { settingsFromEnv } from "../settings.js";
import { BmaClient } from "../bma.js";
import { LiveRunner } from "../runners.js";
import { renderHtml, renderMarkdown } from "../reports.js";

const env = {
  DATA_MODE: "live", EXPECTED_ACCOUNT_ID: "111122223333",
  APP_REGION: "us-east-1", TARGET_REGION: "ap-northeast-2",
  BMA_MODEL: "openai.gpt-6-luna", AGENT_BACKEND: "bma",
  BMA_RUNTIME_ARN: "arn:aws:bedrock-agentcore:us-east-1:111122223333:runtime/demo-123",
  BMA_SESSION_ROLE_ARN: "arn:aws:iam::111122223333:role/BmaSession",
  APP_ACCESS_TOKEN: "fixture-access-token-is-not-a-secret",
  APP_STATE_BUCKET: "fixture-bma-app-state",
};

test("the BMA request uses the east Mantle endpoint, signature and exact regional model", async () => {
  const settings = settingsFromEnv({ ...env, AWS_REGION: "us-west-2" });
  const client = new BmaClient(settings, {
    credentials: { accessKeyId: "fixture", secretAccessKey: "fixture" },
    fetchImpl: async (url, options) => {
      assert.match(url, /^https:\/\/bedrock-mantle\.us-east-1\.api\.aws\//);
      assert.match(options.headers.authorization, /us-east-1\/bedrock-mantle\/aws4_request/);
      const body = JSON.parse(options.body);
      assert.equal(body.agent.model, "openai.gpt-6-luna");
      assert.equal(body.environment.runtime_arn, env.BMA_RUNTIME_ARN);
      return Response.json({ id: "session-east" });
    },
  });
  assert.equal(await client.createSession("서울 EC2 조회"), "session-east");
  assert.equal(settings.targetRegion, "ap-northeast-2");
  assert.throws(() => settingsFromEnv({ ...env, BMA_RUNTIME_ARN: env.BMA_RUNTIME_ARN.replace("us-east-1", "us-west-2") }),
    /Runtime ARN/);
});

test("BMA completion and reports identify the actual regional model even when evidence is empty", async () => {
  const settings = settingsFromEnv(env);
  const client = {
    async *createSessionEvents() {
      yield { type: "agent.session.created", session: { id: "session-east" } };
      yield { type: "agent.session.turn.completed" };
    },
    async listItems() { return { items: [], complete: true }; },
    async cancel() {},
  };
  const events = [];
  for await (const event of new LiveRunner(settings, () => client).stream("서울 조회")) events.push(event);
  const result = events.at(-1);
  assert.equal(result.model, "openai.gpt-6-luna");
  assert.equal(result.agent_backend, "bma");
  assert.equal(result.model_processing_scope, "app_region");
  assert.equal(result.status, "failed");
  const record = {
    ...result, id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", prompt: "서울 조회",
    created_at: "2026-10-27T04:00:00Z", mode: "live", language: "ko",
    account_id: env.EXPECTED_ACCOUNT_ID, app_region: "us-east-1", target_region: "ap-northeast-2",
  };
  for (const text of [renderMarkdown(record), renderHtml(record)]) {
    assert.match(text, /us-east-1/);
    assert.match(text, /openai\.gpt-6-luna/);
    assert.doesNotMatch(text, /us-west-2|global\.openai\.gpt-6-luna/);
  }
});
