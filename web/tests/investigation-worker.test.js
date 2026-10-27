import assert from "node:assert/strict";
import test from "node:test";
import { createInvestigationWorker } from "../investigation-worker.js";
import { settingsFromEnv } from "../settings.js";

const event = {
  investigation_id: "11111111-1111-4111-8111-111111111111",
  run_id: "22222222-2222-4222-8222-222222222222",
};
const env = {
  DATA_MODE: "live", EXPECTED_ACCOUNT_ID: "123456789012",
  APP_REGION: "us-east-1", TARGET_REGION: "ap-northeast-2", AGENT_BACKEND: "bma",
  BMA_MODEL: "openai.gpt-6-luna", BMA_RUNTIME_ARN: "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/example",
  BMA_SESSION_ROLE_ARN: "arn:aws:iam::123456789012:role/BmaSession", APP_STATE_BUCKET: "sample-state",
};

test("worker settings skip only the access key requirement while retaining live boundary validation", () => {
  assert.throws(() => settingsFromEnv(env), /APP_ACCESS_TOKEN/);
  const settings = settingsFromEnv(env, { requireAccessToken: false });
  assert.equal(settings.accessToken, "");
  assert.equal(settings.appRegion, "us-east-1");
  for (const patch of [
    { EXPECTED_ACCOUNT_ID: "bad" }, { APP_REGION: "ap-northeast-2" }, { TARGET_REGION: "us-east-1" },
    { BMA_RUNTIME_ARN: "arn:aws:bedrock-agentcore:us-east-1:999988887777:runtime/example" },
    { BMA_SESSION_ROLE_ARN: "arn:aws:iam::999988887777:role/BmaSession" },
    { APP_STATE_BUCKET: "" }, { BMA_MODEL: "" }, { MAX_PAGES: "11" },
  ]) assert.throws(() => settingsFromEnv({ ...env, ...patch }, { requireAccessToken: false }));
});

test("worker ARN is optional and accepts only a same-account unqualified Virginia Lambda function", () => {
  assert.equal(settingsFromEnv(env, { requireAccessToken: false }).investigationWorkerArn, "");
  const valid = "arn:aws:lambda:us-east-1:123456789012:function:desk-investigation-worker";
  assert.equal(settingsFromEnv({ ...env, INVESTIGATION_WORKER_ARN: valid }, { requireAccessToken: false }).investigationWorkerArn, valid);
  for (const invalid of [
    "arn:aws:lambda:ap-northeast-2:123456789012:function:desk-investigation-worker",
    "arn:aws:lambda:us-east-1:999988887777:function:desk-investigation-worker",
    "arn:aws:lambda:us-east-1:123456789012:function:desk-investigation-worker:unreviewed",
    "desk-investigation-worker", "arn:aws:lambda:us-east-1:123456789012:layer:desk",
  ]) assert.throws(() => settingsFromEnv({ ...env, INVESTIGATION_WORKER_ARN: invalid }, { requireAccessToken: false }),
    /Invalid investigation worker ARN/);
});

test("worker verifies STS before invoking the executor and forwards only validated IDs", async () => {
  const calls = [], store = {}, reportStore = {};
  const run = createInvestigationWorker({
    env, store, reportStore,
    stsClient: { async send(command) {
      calls.push(command.constructor.name);
      return { Account: "123456789012" };
    } },
    async execute(dependencies, ids) {
      calls.push("execute");
      assert.equal(dependencies.store, store);
      assert.equal(dependencies.reportStore, reportStore);
      assert.equal(dependencies.settings.accessToken, "");
      assert.deepEqual(ids, event);
      return { status: "complete" };
    },
  });
  assert.deepEqual(await run(event), { status: "complete" });
  assert.deepEqual(calls, ["GetCallerIdentityCommand", "execute"]);
});

test("invalid events are rejected before STS or storage can be reached", async () => {
  let calls = 0;
  const run = createInvestigationWorker({
    env, store: {}, reportStore: {}, stsClient: { async send() { calls++; } },
    async execute() { calls++; },
  });
  for (const value of [null, [], {}, { ...event, account_id: "999988887777" }, { ...event, run_id: "../secret" },
    { ...event, investigation_id: null }, { ...event, force: true }]) {
    await assert.rejects(run(value), /InvalidInvestigationEvent/);
  }
  assert.equal(calls, 0);
});

test("STS mismatch and failure prevent execution without exposing identity provider detail", async () => {
  let executed = 0;
  for (const failure of ["mismatch", "error"]) {
    const run = createInvestigationWorker({
      env, store: {}, reportStore: {},
      stsClient: { async send() {
        if (failure === "error") throw new Error("credentials and private STS detail");
        return { Account: "999988887777" };
      } },
      async execute() { executed++; },
    });
    await assert.rejects(run(event), (error) => {
      assert.equal(error.code, failure === "error" ? "AccountVerificationFailed" : "AccountMismatch");
      assert.doesNotMatch(error.message, /credentials|999988887777/);
      return true;
    });
  }
  assert.equal(executed, 0);
});
