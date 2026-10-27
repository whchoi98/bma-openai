import assert from "node:assert/strict";
import { Readable } from "node:stream";
import test from "node:test";
import samples from "../sample-data.json" with { type: "json" };
import {
  InvestigationConflict, MemoryInvestigationStore, S3InvestigationStore, investigationPrefix,
} from "../investigation-store.js";

const settings = { accountId: "123456789012", appRegion: "us-east-1", targetRegion: "ap-northeast-2",
  mode: "live", stateBucket: "investigation-state" };
const id = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const prefix = "investigations/123456789012/ap-northeast-2/";
const sessionKey = (n) => `${prefix}sessions/${id(n)}.json`;
const turnKey = (n) => `${prefix}turns/${id(n)}.json`;
const session = (n = 1, extra = {}) => ({
  id: id(n), account_id: settings.accountId, app_region: settings.appRegion,
  target_region: settings.targetRegion, mode: settings.mode, created_at: `2026-10-27T03:${String(n).padStart(2, "0")}:00Z`,
  updated_at: "2026-10-27T04:00:00Z", expires_at: "2026-10-27T09:00:00Z",
  title: "Inspect account 123456789012", status: "queued", active_run_id: id(n),
  bma_session_id: "private-bma-session", worker_token: "private-worker-token", lease_until: "private-lease",
  procedure: { id: "inventory", version: "1.0.0", sha256: "a".repeat(64),
    name: { ko: "리소스", en: "Inventory" }, description: { ko: "설명", en: "Description" },
    steps: [{ id: "account", label: { ko: "계정", en: "Account" }, tools: ["get_account_context"] }],
    skills: [{ name: "private-skill", markdown: "private-instructions" }] },
  turns: [{ id: id(n), prompt: "Inspect account 123456789012", language: "en", status: "queued",
    created_at: "2026-10-27T03:00:00Z", bma_turn_id: "private-bma-turn" }],
  ...extra,
});
const turn = (n = 1, extra = {}) => ({
  ...session(n), investigation_id: id(n), phase: "queued", prompt: "Inspect resources", language: "en",
  answer: "", evidence: [], errors: [], bma_turn_id: "private-bma-turn", ...extra,
});
const error = (name, status) => Object.assign(new Error(name), { name,
  ...(status === undefined ? {} : { $metadata: { httpStatusCode: status } }) });

// The S3 boundary is external; this fake enforces conditional writes and paginates
// real serialized objects so assertions cover the store, not canned responses.
function fakeS3() {
  const objects = new Map(), calls = [];
  let version = 0;
  const fake = { objects, calls, intercept: null, client: { async send(command) {
    const p = command.input, type = command.constructor.name;
    calls.push({ type, ...p });
    const intercepted = await fake.intercept?.(type, p);
    if (intercepted !== undefined) return intercepted;
    if (type === "PutObjectCommand") {
      const current = objects.get(p.Key);
      if (p.IfNoneMatch === "*" && current) throw error("PreconditionFailed", 412);
      if (p.IfMatch !== undefined && p.IfMatch !== current?.etag) throw error("PreconditionFailed", 412);
      const etag = `"version-${++version}"`;
      objects.set(p.Key, { body: String(p.Body), etag });
      return { ETag: etag };
    }
    if (type === "GetObjectCommand") {
      const current = objects.get(p.Key);
      if (!current) throw error("NoSuchKey", 404);
      return { ETag: current.etag, ContentLength: Buffer.byteLength(current.body),
        Body: Readable.from([Buffer.from(current.body)]) };
    }
    assert.equal(type, "ListObjectsV2Command");
    const after = p.ContinuationToken?.replace(/^after:/, "") || "";
    const keys = [...objects.keys()].filter((key) => key.startsWith(p.Prefix) && key > after).sort();
    const selected = keys.slice(0, p.MaxKeys), truncated = keys.length > selected.length;
    return { Contents: selected.map((Key) => ({ Key })), IsTruncated: truncated,
      ...(truncated ? { NextContinuationToken: "after:" + selected.at(-1) } : {}) };
  } } };
  return fake;
}

for (const kind of ["memory", "s3"]) {
  const setup = () => {
    const fake = fakeS3();
    return { fake, store: kind === "memory" ? new MemoryInvestigationStore(settings) :
      new S3InvestigationStore(settings, fake.client) };
  };

  test(`${kind}: sessions and turns round-trip independently and returned objects are detached`, async () => {
    const { store } = setup(), original = session();
    assert.equal(await store.getSession(id(1)), null);
    assert.equal(await store.getTurn(id(1)), null);
    const saved = await store.createSession(original);
    assert.equal(typeof saved.etag, "string");
    assert.deepEqual(saved.value, original);
    original.title = "mutated input"; saved.value.title = "mutated output";
    assert.equal((await store.getSession(id(1))).value.title, "Inspect account 123456789012");
    const savedTurn = await store.createTurn(turn());
    assert.deepEqual((await store.getTurn(id(1))).value, savedTurn.value);
    assert.equal((await store.getSession(id(1))).value.bma_session_id, "private-bma-session");
  });

  test(`${kind}: concurrent create and stale updates have exactly one winner`, async () => {
    const { store } = setup();
    const creates = await Promise.allSettled([store.createSession(session()), store.createSession(session())]);
    assert.equal(creates.filter((result) => result.status === "fulfilled").length, 1);
    assert.ok(creates.find((result) => result.status === "rejected").reason instanceof InvestigationConflict);
    const saved = await store.getSession(id(1));
    const updates = await Promise.allSettled([
      store.putSession({ ...saved.value, active_run_id: id(2) }, saved.etag),
      store.putSession({ ...saved.value, active_run_id: id(3) }, saved.etag),
    ]);
    assert.equal(updates.filter((result) => result.status === "fulfilled").length, 1);
    assert.ok(updates.find((result) => result.status === "rejected").reason instanceof InvestigationConflict);
    const current = await store.getSession(id(1));
    assert.notEqual(current.etag, saved.etag);
    assert.ok([id(2), id(3)].includes(current.value.active_run_id));
    const firstTurn = await store.createTurn(turn());
    await store.putTurn({ ...firstTurn.value, worker_token: "winner" }, firstTurn.etag);
    await assert.rejects(store.putTurn({ ...firstTurn.value, worker_token: "stale" }, firstTurn.etag),
      InvestigationConflict);
    assert.equal((await store.getTurn(id(1))).value.worker_token, "winner");
  });

  test(`${kind}: missing, wildcard and malformed ETags cannot cause unconditional updates`, async () => {
    const { store } = setup();
    await store.createSession(session());
    for (const etag of [undefined, null, "", "*", '"one","two"', "bad\netag"]) {
      await assert.rejects(store.putSession(session(), etag), /InvalidInvestigationETag/);
      await assert.rejects(store.putTurn(turn(), etag), /InvalidInvestigationETag/);
    }
    await assert.rejects(store.putSession(session(2), '"missing"'), InvestigationConflict);
  });

  test(`${kind}: foreign and incomplete scopes and unsafe identifiers are rejected`, async () => {
    const { store, fake } = setup();
    for (const extra of [
      { account_id: "999988887777" }, { app_region: "ap-northeast-2" },
      { target_region: "us-east-1" }, { mode: "sample" }, { account_id: undefined },
      { app_region: undefined }, { target_region: undefined }, { mode: undefined },
      { id: "../../private" }, { created_at: "not-a-date" }, { active_run_id: "../other" },
      { turns: [{ id: "not-a-uuid" }] },
    ]) await assert.rejects(store.createSession(session(1, extra)), /Invalid|Mismatch/);
    await assert.rejects(store.createTurn(turn(1, { investigation_id: "../session" })), /Invalid/);
    await assert.rejects(store.getSession("../escape"), /Invalid/);
    await assert.rejects(store.getTurn("../escape"), /Invalid/);
    assert.equal(fake.calls.length, 0);
  });

  test(`${kind}: size and turn limits are checked before any write`, async () => {
    const { store, fake } = setup();
    await assert.rejects(store.createSession(session(1, { title: "한".repeat(50_000) })), /TooLarge/);
    await assert.rejects(store.createTurn(turn(1, { answer: "x".repeat(4_000_000) })), /TooLarge/);
    await assert.rejects(store.createSession(session(1, { turns: Array.from({ length: 11 },
      (_, n) => ({ id: id(n), created_at: "2026-10-27T03:00:00Z" })) })), /Invalid|TooMany/);
    assert.equal(fake.calls.length, 0);
    assert.equal(await store.getSession(id(1)), null);
  });

  test(`${kind}: public scalar fields cannot carry nested private payloads`, async () => {
    const { store, fake } = setup();
    for (const extra of [
      { title: { bma_session_id: "private-leak" } },
      { updated_at: { worker_token: "private-leak" } },
      { turns: [{ id: id(1), prompt: { bma_turn_id: "private-leak" } }] },
      { procedure: { name: { ko: { instructions: "private-leak" } } } },
      { procedure: { id: { bma_session_id: "private-leak" } } },
      { procedure: { steps: [{ id: { worker_token: "private-leak" } }] } },
    ]) await assert.rejects(store.createSession(session(1, extra)), /InvalidInvestigation/);
    assert.equal(fake.calls.length, 0);
  });

  test(`${kind}: newest-first pagination contains public fields and preserves routing UUIDs`, async () => {
    const { store } = setup();
    for (const n of [2, 1, 3]) await store.createSession(session(n));
    const first = await store.list({ limit: 2 });
    assert.deepEqual(first.investigations.map((item) => item.id), [id(3), id(2)]);
    assert.equal(first.complete, false);
    const second = await store.list({ limit: 2, cursor: first.next_cursor });
    assert.deepEqual(second.investigations.map((item) => item.id), [id(1)]);
    assert.equal(second.complete, true); assert.equal(second.next_cursor, null);
    assert.deepEqual(Object.keys(first.investigations[0]).sort(), [
      "active_run_id", "created_at", "expires_at", "id", "procedure", "status", "title", "turns", "updated_at",
    ].sort());
    assert.equal(first.investigations[0].turns[0].id, id(3));
    assert.equal(first.investigations[0].active_run_id, id(3));
    assert.match(first.investigations[0].title, /\*{9}012/);
    assert.doesNotMatch(JSON.stringify(first.investigations), /123456789012|private-|bma_|lease|worker_token|skills/);
    const saved = await store.getSession(id(3));
    await store.putSession({ ...saved.value, status: "complete", active_run_id: null }, saved.etag);
    assert.equal((await store.list()).investigations[0].status, "complete");
  });

  test(`${kind}: cursors cannot cross account, bucket, mode or store kind`, async () => {
    const { store } = setup();
    await store.createSession(session(1)); await store.createSession(session(2));
    const { next_cursor } = await store.list({ limit: 1 });
    for (const extra of [
      { accountId: "999988887777" }, { stateBucket: "other-bucket" }, { mode: "sample" },
    ]) {
      const changed = kind === "memory" ? new MemoryInvestigationStore({ ...settings, ...extra }) :
        new S3InvestigationStore({ ...settings, ...extra }, { send: () => assert.fail("foreign cursor queried S3") });
      await assert.rejects(changed.list({ cursor: next_cursor }), /InvalidInvestigationCursor/);
    }
    const changedKind = kind === "memory" ? new S3InvestigationStore(settings, {
      send: () => assert.fail("foreign cursor queried S3"),
    }) : new MemoryInvestigationStore(settings);
    await assert.rejects(changedKind.list({ cursor: next_cursor }), /InvalidInvestigationCursor/);
    for (const cursor of ["../escape", "a".repeat(4097), 1,
      Buffer.from(JSON.stringify({ version: 1, kind, token: "../foreign" })).toString("base64url")]) {
      await assert.rejects(store.list({ cursor }), /InvalidInvestigationCursor/);
    }
    for (const limit of [0, 21, -1, 1.5, "2"]) {
      await assert.rejects(store.list({ limit }), /InvalidInvestigationLimit/);
    }
  });

  test(`${kind}: immutable creation times and turn ownership cannot change`, async () => {
    const { store } = setup();
    const saved = await store.createSession(session());
    await assert.rejects(store.putSession({ ...saved.value, created_at: "2026-10-27T05:00:00Z" },
      saved.etag), /ImmutableInvestigation/);
    const savedTurn = await store.createTurn(turn());
    await assert.rejects(store.putTurn({ ...savedTurn.value, investigation_id: id(2) },
      savedTurn.etag), /ImmutableInvestigation/);
  });

  test(`${kind}: the chosen procedure expiry and established BMA session are immutable`, async () => {
    const { store } = setup();
    const saved = await store.createSession(session());
    for (const extra of [
      { expires_at: "2026-10-28T09:00:00Z" }, { expires_at: undefined },
      { procedure: { ...saved.value.procedure, id: "operations-report" } },
      { procedure: { ...saved.value.procedure, name: { en: "different" } } },
      { bma_session_id: "different-session" }, { bma_session_id: undefined },
    ]) await assert.rejects(store.putSession({ ...saved.value, ...extra }, saved.etag), /ImmutableInvestigation/);
    const pending = await store.createSession(session(2, { bma_session_id: undefined }));
    const assigned = await store.putSession({ ...pending.value, bma_session_id: "first-session" }, pending.etag);
    assert.equal(assigned.value.bma_session_id, "first-session");
  });

  test(`${kind}: stored evidence rejects foreign scope and removes raw model fields`, async () => {
    const { store } = setup();
    const observation = { ...samples.list_ec2_instances, account_id: settings.accountId, mode: "live",
      item_id: "item_keep_for_dedup", reasoning: "SECRET",
      scope: { max_resources: 2, raw_model_item: "SECRET" } };
    for (const extra of [
      { account_id: "999988887777" }, { region: "us-west-2" }, { mode: "sample" },
      { data: [{ id: { reasoning: "SECRET" } }] },
    ]) await assert.rejects(store.createTurn(turn(1, { evidence: [{ ...observation, ...extra }] })), /Invalid|Mismatch/);
    const saved = await store.createTurn(turn(1, { evidence: [observation] }));
    assert.equal(saved.value.evidence[0].item_id, "item_keep_for_dedup");
    assert.doesNotMatch(JSON.stringify((await store.getTurn(id(1))).value.evidence), /SECRET|reasoning|raw_model_item/);
    await assert.rejects(store.putTurn({ ...saved.value, result: {
      ...saved.value, id: id(2), investigation_id: id(1),
    } }, saved.etag), /Invalid|Mismatch/);
  });
}

test("fixed account, region and mode settings are validated", () => {
  assert.equal(investigationPrefix(settings), prefix);
  for (const extra of [
    { accountId: "" }, { accountId: "../../private" }, { appRegion: "ap-northeast-2" },
    { targetRegion: "us-east-1" }, { mode: "unknown" }, { mode: undefined },
  ]) {
    assert.throws(() => new MemoryInvestigationStore({ ...settings, ...extra }), /InvalidInvestigation/);
    assert.throws(() => new S3InvestigationStore({ ...settings, ...extra }, fakeS3().client), /InvalidInvestigation/);
  }
});

test("S3 state and index writes use owner checks, encryption and conditional preconditions", async () => {
  const fake = fakeS3(), store = new S3InvestigationStore(settings, fake.client);
  const saved = await store.createSession(session());
  await store.putSession({ ...saved.value, status: "running" }, saved.etag);
  await store.createTurn(turn()); await store.getTurn(id(1)); await store.list();
  for (const call of fake.calls) {
    assert.equal(call.ExpectedBucketOwner, settings.accountId);
    assert.equal(call.Bucket, settings.stateBucket);
    assert.ok(call.Key?.startsWith(prefix) || call.Prefix === prefix + "index/");
    if (call.type === "PutObjectCommand") {
      assert.equal(call.ContentType, "application/json"); assert.equal(call.ServerSideEncryption, "AES256");
      assert.ok(call.IfNoneMatch === "*" || typeof call.IfMatch === "string");
      assert.notEqual(call.IfNoneMatch !== undefined, call.IfMatch !== undefined);
    }
  }
  assert.equal(fake.calls.find((call) => call.Key === sessionKey(1) && call.IfMatch)?.IfMatch, saved.etag);
  assert.equal(fake.objects.size, 3);
  const index = [...fake.objects].find(([key]) => key.includes("/index/"))[1];
  assert.doesNotMatch(index.body, /private-|bma_|worker_token|lease|skills/);
});

test("only 409 and 412 precondition failures become conflicts; access and transport errors survive", async () => {
  for (const [status, name] of [[409, "ConditionalRequestConflict"], [412, "PreconditionFailed"],
    [403, "AccessDenied"], [500, "InternalError"], [undefined, "TimeoutError"], [undefined, "PreconditionFailed"]]) {
    const failure = error(name, status);
    const store = new S3InvestigationStore(settings, { async send() { throw failure; } });
    await assert.rejects(store.createTurn(turn()), (actual) =>
      [409, 412].includes(status) ? actual instanceof InvestigationConflict && actual.cause === failure : actual === failure);
    await assert.rejects(store.getTurn(id(1)), (actual) => actual === failure);
  }
  const store = new S3InvestigationStore(settings, { async send() { throw error("NoSuchBucket", 404); } });
  await assert.rejects(store.getSession(id(1)), /NoSuchBucket/);
});

test("S3 reads reject foreign scope, substituted identifiers, missing ETags and oversized streams", async () => {
  const fake = fakeS3(), store = new S3InvestigationStore(settings, fake.client);
  for (const value of [
    session(1, { account_id: "999988887777" }), session(2), session(1, { mode: "sample" }),
  ]) {
    fake.objects.set(sessionKey(1), { body: JSON.stringify(value), etag: '"one"' });
    await assert.rejects(store.getSession(id(1)), /Invalid|Mismatch/);
  }
  fake.objects.set(sessionKey(1), { body: JSON.stringify(session()), etag: undefined });
  await assert.rejects(store.getSession(id(1)), /InvalidInvestigationETag/);
  let destroyed = false;
  fake.intercept = () => ({ ETag: '"one"', Body: {
    destroy() { destroyed = true; },
    async *[Symbol.asyncIterator]() { yield Buffer.from("x".repeat(128 * 1024)); yield Buffer.from("x"); },
  } });
  await assert.rejects(store.getSession(id(1)), /TooLarge/);
  assert.equal(destroyed, true);
});

test("S3 denied missing investigation objects require an exact bounded owner-checked absence probe", async () => {
  for (const method of ["getSession", "getTurn"]) {
    const fake = fakeS3(), store = new S3InvestigationStore(settings, fake.client);
    const denied = error("AccessDenied", 403);
    fake.intercept = (type) => { if (type === "GetObjectCommand") throw denied; };
    assert.equal(await store[method](id(1)), null);
    const probe = fake.calls.find((call) => call.type === "ListObjectsV2Command");
    assert.equal(probe.Prefix, method === "getSession" ? sessionKey(1) : turnKey(1));
    assert.equal(probe.MaxKeys, 1);
    assert.equal(probe.ExpectedBucketOwner, settings.accountId);
    assert.equal(probe.Bucket, settings.stateBucket);
    assert.equal(probe.ContinuationToken, undefined);
    assert.equal(probe.Delimiter, undefined);
  }
});

test("S3 denied existing investigations and inconclusive probes preserve the original error", async () => {
  const denied = error("AccessDenied", 403);
  for (const response of [
    { Contents: [{ Key: sessionKey(1) }], IsTruncated: false },
    { Contents: [], IsTruncated: true },
    { Contents: [] },
    { Contents: null, IsTruncated: false },
    { Contents: [{ Key: "unrelated/private.json" }], IsTruncated: false },
    { Contents: [{ Key: sessionKey(1) + ".a" }, { Key: sessionKey(1) + ".b" }], IsTruncated: false },
    { Contents: [], IsTruncated: false, KeyCount: 1 },
    { Contents: [], IsTruncated: false, NextContinuationToken: "unexamined" },
    { Contents: [], IsTruncated: false, ContinuationToken: "unexpected-page" },
    { Contents: [], IsTruncated: false, StartAfter: sessionKey(1) },
    { Contents: [], IsTruncated: false, Prefix: "foreign/" },
    { Contents: [], IsTruncated: false, CommonPrefixes: [{ Prefix: sessionKey(1) }] },
    new Error("probe transport failure"),
  ]) {
    const store = new S3InvestigationStore(settings, { async send(command) {
      if (command.constructor.name === "GetObjectCommand") throw denied;
      if (response instanceof Error) throw response;
      return response;
    } });
    await assert.rejects(store.getSession(id(1)), (actual) => actual === denied);
  }
});

test("S3 exact-prefix sibling objects can prove absence without treating non-403 failures as missing", async () => {
  const fake = fakeS3(), store = new S3InvestigationStore(settings, fake.client);
  fake.intercept = (type) => {
    if (type === "GetObjectCommand") throw error("Forbidden", 403);
    return { Contents: [{ Key: sessionKey(1) + ".backup" }], IsTruncated: false, KeyCount: 1 };
  };
  assert.equal(await store.getSession(id(1)), null);
  fake.calls.length = 0;
  const unavailable = error("InternalError", 500);
  fake.intercept = () => { throw unavailable; };
  await assert.rejects(store.getSession(id(1)), (actual) => actual === unavailable);
  assert.equal(fake.calls.length, 1);
  fake.calls.length = 0;
  await assert.rejects(store.read("other/private.json", 100), /InvalidInvestigationKey/);
  assert.equal(fake.calls.length, 0);
});

test("S3 can create the first index when its missing GetObject is denied", async () => {
  const fake = fakeS3(), store = new S3InvestigationStore(settings, fake.client);
  fake.intercept = (type, p) => {
    if (type === "GetObjectCommand" && p.Key.includes("/index/") && !fake.objects.has(p.Key)) {
      throw error("AccessDenied", 403);
    }
  };
  await store.createSession(session());
  const probe = fake.calls.find((call) => call.type === "ListObjectsV2Command");
  assert.match(probe.Prefix, /^investigations\/123456789012\/ap-northeast-2\/index\/\d{13}-[a-f0-9-]+\.json$/);
  assert.equal(probe.MaxKeys, 1);
  assert.equal(probe.ExpectedBucketOwner, settings.accountId);
  assert.equal((await store.list()).investigations[0].id, id(1));
});

test("S3 index failure exposes committed state and ETag and does not turn into a conflict", async () => {
  const fake = fakeS3(), store = new S3InvestigationStore(settings, fake.client);
  const failure = error("AccessDenied", 403);
  fake.intercept = (type, p) => {
    if (type === "PutObjectCommand" && p.Key.includes("/index/")) throw failure;
  };
  let savedError;
  await assert.rejects(store.createSession(session()), (actual) => {
    savedError = actual;
    return actual.name === "InvestigationIndexWriteFailed" && actual.recordSaved === true &&
      actual.cause === failure && !(actual instanceof InvestigationConflict);
  });
  const persisted = await store.getSession(id(1));
  assert.equal(savedError.etag, persisted.etag);
  assert.deepEqual(savedError.value, persisted.value);
  fake.intercept = null;
  await store.putSession({ ...persisted.value, status: "running" }, persisted.etag);
  assert.equal((await store.list()).investigations[0].status, "running");
});

test("S3 an older writer cannot replace an index already updated by a newer session writer", async () => {
  const fake = fakeS3(), store = new S3InvestigationStore(settings, fake.client);
  const saved = await store.createSession(session());
  let unblock, blocked;
  const reached = new Promise((resolve) => { blocked = resolve; });
  const waiting = new Promise((resolve) => { unblock = resolve; });
  let pauseOnce = true;
  fake.intercept = async (type, p) => {
    if (type === "PutObjectCommand" && p.Key.includes("/index/") &&
        String(p.Body).includes('"status":"running"') && pauseOnce) {
      pauseOnce = false; blocked(); await waiting;
    }
  };
  const oldWrite = store.putSession({ ...saved.value, status: "running" }, saved.etag);
  await reached;
  const current = await store.getSession(id(1));
  await store.putSession({ ...current.value, status: "complete" }, current.etag);
  unblock(); await oldWrite;
  assert.equal((await store.list()).investigations[0].status, "complete");
});

test("S3 list rejects malformed pages and leaked or foreign index fields", async () => {
  const fake = fakeS3(), store = new S3InvestigationStore(settings, fake.client);
  for (const page of [
    { Contents: [], IsTruncated: true }, { Contents: [], IsTruncated: "false" },
    { Contents: [{ Key: prefix + "sessions/" + id(1) + ".json" }], IsTruncated: false },
  ]) {
    fake.intercept = (type) => type === "ListObjectsV2Command" ? page : undefined;
    await assert.rejects(store.list(), /InvalidInvestigationPage/);
  }
  fake.intercept = null;
  await store.createSession(session());
  const [key, stored] = [...fake.objects].find(([key]) => key.includes("/index/"));
  const original = JSON.parse(stored.body);
  for (const changed of [
    { ...original, account_id: "999988887777" },
    { ...original, summary: { ...original.summary, bma_session_id: "private-leak" } },
    { ...original, summary: { ...original.summary, procedure: {
      ...original.summary.procedure, skills: ["private-leak"],
    } } },
    { ...original, summary: { ...original.summary, title: { bma_session_id: "private-leak" } } },
    { ...original, summary: { ...original.summary, procedure: {
      ...original.summary.procedure, name: { en: { bma_session_id: "private-leak" } },
    } } },
  ]) {
    fake.objects.set(key, { ...stored, body: JSON.stringify(changed) });
    await assert.rejects(store.list(), /Invalid|Mismatch/);
  }
});

test("S3 index conflicts have a bounded retry and still report the committed session", async () => {
  const fake = fakeS3(), store = new S3InvestigationStore(settings, fake.client);
  let attempts = 0;
  fake.intercept = (type, p) => {
    if (type === "PutObjectCommand" && p.Key.includes("/index/")) {
      attempts++;
      throw error("PreconditionFailed", 412);
    }
  };
  await assert.rejects(store.createSession(session()), (actual) => actual.recordSaved === true &&
    actual.cause instanceof InvestigationConflict && actual.value.id === id(1) && typeof actual.etag === "string");
  assert.equal(attempts, 4);
  assert.equal((await store.getSession(id(1))).value.id, id(1));
});

test("S3 invalid write receipts report saved state instead of pretending the write failed", async () => {
  const fake = fakeS3(), store = new S3InvestigationStore(settings, fake.client);
  fake.intercept = (type) => type === "PutObjectCommand" ? {} : undefined;
  await assert.rejects(store.createTurn(turn()), (actual) => actual.recordSaved === true &&
    actual.name === "InvestigationWriteReceiptInvalid" && actual.value.id === id(1));
});

test("S3 list propagates unavailable or denied index reads rather than returning an empty list", async () => {
  const fake = fakeS3(), store = new S3InvestigationStore(settings, fake.client);
  await store.createSession(session());
  for (const failure of [error("AccessDenied", 403), error("TimeoutError")]) {
    fake.intercept = (type) => { if (type === "GetObjectCommand") throw failure; };
    await assert.rejects(store.list(), (actual) => actual === failure);
  }
});

test("sample list masking never changes session, active run or turn UUIDs", async () => {
  const sampleSettings = { ...settings, accountId: "000000000000", mode: "sample" };
  const store = new MemoryInvestigationStore(sampleSettings);
  const value = session(1, { account_id: "000000000000", mode: "sample" });
  await store.createSession(value);
  const listed = (await store.list()).investigations[0];
  assert.equal(listed.id, id(1)); assert.equal(listed.active_run_id, id(1));
  assert.equal(listed.turns[0].id, id(1));
});

test("S3 reads validate nested persisted evidence before it can reach public snapshots", async () => {
  const fake = fakeS3(), store = new S3InvestigationStore(settings, fake.client);
  const poisoned = turn(1, { evidence: [{ ...samples.list_ec2_instances, mode: "live",
    account_id: "999988887777" }] });
  fake.objects.set(turnKey(1), { body: JSON.stringify(poisoned), etag: '"one"' });
  await assert.rejects(store.getTurn(id(1)), /Mismatch/);
  fake.objects.set(turnKey(1), { body: JSON.stringify(turn(1, { answer: { reasoning: "SECRET" } })), etag: '"one"' });
  await assert.rejects(store.getTurn(id(1)), /Invalid/);
});
