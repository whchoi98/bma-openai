import assert from "node:assert/strict";
import test from "node:test";
import { BmaClient } from "../bma.js";

const settings = {
  appRegion: "us-east-1", targetRegion: "ap-northeast-2",
  model: "openai.gpt-6-luna", runtimeArn: "arn:aws:bedrock-agentcore:us-east-1:111122223333:runtime/example",
  sessionRoleArn: "arn:aws:iam::111122223333:role/example", maxTurnSeconds: 300,
};
const credentials = { accessKeyId: "fixture", secretAccessKey: "fixture" };

test("investigation session creation has no initial inference and pins procedure instructions", async () => {
  const requests = [];
  const client = new BmaClient(settings, { credentials, fetchImpl: async (url, options) => {
    requests.push({ url, body: JSON.parse(options.body) });
    return Response.json({ id: "sess_investigation" });
  } });
  assert.equal(typeof client.createInvestigationSession, "function");
  assert.equal(await client.createInvestigationSession("approved procedure", "en"), "sess_investigation");
  assert.equal(requests[0].body.input, undefined);
  assert.equal(requests[0].body.agent.model, settings.model);
  assert.match(requests[0].body.agent.instructions, /approved procedure/);
  assert.match(requests[0].body.agent.instructions, /per-turn settings override default language or time/);
  assert.doesNotMatch(requests[0].body.agent.instructions, /Respond in English\. This applies to the final answer/);
  assert.equal(requests[0].body.stream, false);
});

test("follow-up input uses the documented event and an ambiguous POST is not repeated", async () => {
  let calls = 0;
  const client = new BmaClient(settings, { credentials, fetchImpl: async (url, options) => {
    calls++;
    assert.match(url, /sessions\/sess_investigation\/events$/);
    const body = JSON.parse(options.body);
    assert.equal(body.events[0].type, "agent.session.input.message");
    assert.equal(body.events[0].input[0].content[0].text, "next question");
    throw new TypeError("connection lost after acceptance");
  } });
  assert.equal(typeof client.submitInput, "function");
  await assert.rejects(client.submitInput("sess_investigation", "next question"));
  assert.equal(calls, 1);
});

test("bounded durable items accept a previous cursor for multi-turn reconciliation", async () => {
  const client = new BmaClient(settings, { credentials, fetchImpl: async (url) => {
    assert.equal(new URL(url).searchParams.get("after"), "prior-item");
    return Response.json({ data: [{ id: "new-item", turn_id: "turn_2" }], has_more: false, last_id: "new-item" });
  } });
  const result = await client.listItems("sess_investigation", { after: "prior-item" });
  assert.equal(result.last_id, "new-item");
  assert.equal(result.complete, true);
});
