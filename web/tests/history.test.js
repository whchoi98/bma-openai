import assert from "node:assert/strict";
import { Readable } from "node:stream";
import test from "node:test";
import { MemoryStore, S3Store } from "../stores.js";

const settings = { mode: "live", accountId: "123456789012", appRegion: "us-east-1",
  targetRegion: "ap-northeast-2", stateBucket: "demo-history" };
const id = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const record = (n = 1, extra = {}) => ({
  id: id(n), created_at: `2026-10-27T03:${String(n % 60).padStart(2, "0")}:00Z`,
  account_id: settings.accountId, app_region: settings.appRegion, target_region: settings.targetRegion,
  mode: "live", language: "en", status: "complete", report_available: true,
  supported_services: ["ec2", "s3", "vpc"], requested_services: ["vpc"],
  prompt: "Account ID: 1234**5678**9012, list VPCs", answer: "Saved answer", errors: [],
  evidence: [{ account_id: settings.accountId, region: settings.targetRegion, mode: "live",
    service: "vpc", tool: "list_vpcs", status: "ok", observed_at: "2026-10-27T03:00:00Z",
    resource_count: 1, pagination_complete: true, truncated: false, permission_denied: false,
    scope: { max_resources: 10, vpc_id: "vpc-1" },
    api_calls: [{ service: "ec2", api: "DescribeVpcs", region: settings.targetRegion, success: true }],
    data: [{ id: "vpc-1", private_name: "evidence-only-value" }], errors: [] }],
  ...extra,
});

function fakeS3() {
  const objects = new Map(), calls = [];
  const client = { async send(command) {
    const p = command.input; calls.push({ type: command.constructor.name, ...p });
    assert.equal(p.Bucket, settings.stateBucket);
    if (command.constructor.name === "PutObjectCommand") { objects.set(p.Key, String(p.Body)); return {}; }
    if (command.constructor.name === "GetObjectCommand") {
      if (!objects.has(p.Key)) throw Object.assign(new Error("not found"), { name: "NoSuchKey" });
      return { Body: Readable.from([Buffer.from(objects.get(p.Key))]) };
    }
    assert.equal(command.constructor.name, "ListObjectsV2Command");
    const after = p.ContinuationToken?.replace(/^after:/, "") || "";
    const keys = [...objects.keys()].filter((key) => key.startsWith(p.Prefix) && key > after).sort();
    const selected = keys.slice(0, p.MaxKeys);
    return { Contents: selected.map((Key) => ({ Key })), IsTruncated: keys.length > selected.length,
      ...(keys.length > selected.length ? { NextContinuationToken: "after:" + selected.at(-1) } : {}) };
  } };
  return { client, objects, calls };
}

test("memory history uses creation time and cursors instead of insertion order", async () => {
  const store = new MemoryStore(settings);
  await store.put(record(3)); await store.put(record(1)); await store.put(record(2));
  assert.equal(typeof store.list, "function", "store must expose bounded report history");
  const first = await store.list({ limit: 2 });
  assert.deepEqual(first.runs.map((r) => r.id), [id(3), id(2)]);
  assert.equal(first.complete, false);
  const second = await store.list({ limit: 2, cursor: first.next_cursor });
  assert.deepEqual(second.runs.map((r) => r.id), [id(1)]);
  assert.equal(second.next_cursor, null); assert.equal(second.complete, true);
  assert.doesNotMatch(JSON.stringify(first.runs), /123456789012|evidence-only-value/);
  assert.match(first.runs[0].prompt, /\*{9}012/);
  assert.equal((await store.get(id(1))).answer, "Saved answer");
});

test("history bounds limits and rejects malformed or foreign-scope cursors", async () => {
  const store = new MemoryStore(settings);
  for (const limit of [0, 21, -1, 1.1, "2", NaN]) {
    await assert.rejects(store.list({ limit }), /InvalidHistoryLimit/);
  }
  await store.put(record(1)); await store.put(record(2));
  const { next_cursor } = await store.list({ limit: 1 });
  const other = new MemoryStore({ ...settings, accountId: "999988887777" });
  await assert.rejects(other.list({ cursor: next_cursor }), /InvalidHistoryCursor/);
  await assert.rejects(store.list({ cursor: "../runs" }), /InvalidHistoryCursor/);
});

test("sample history preserves routing UUIDs through memory and S3 pagination", async () => {
  for (const store of [new MemoryStore(),
    new S3Store({ ...settings, accountId: "000000000000", mode: "sample" }, fakeS3().client)]) {
    for (const n of [1, 2]) {
      const value = record(n, { account_id: "000000000000", mode: "sample" });
      value.evidence[0].account_id = "000000000000"; value.evidence[0].mode = "sample";
      await store.put(value);
    }
    const first = await store.list({ limit: 1 });
    assert.deepEqual(first.runs.map((run) => run.id), [id(2)]);
    const second = await store.list({ limit: 1, cursor: first.next_cursor });
    assert.deepEqual(second.runs.map((run) => run.id), [id(1)]);
    assert.equal(second.complete, true);
    assert.equal((await store.get(second.runs[0].id)).id, id(1));
  }
});

test("history summaries retain service scope and incomplete query results without evidence rows", async () => {
  const { summarizeHistoryRecord } = await import("../history.js");
  const value = record(1);
  value.evidence[0].status = "partial"; value.evidence[0].pagination_complete = false;
  value.evidence[0].truncated = true; value.errors = ["QueryLimitReached"]; value.status = "partial";
  const summary = summarizeHistoryRecord(value, settings);
  assert.deepEqual(summary.queried_services, ["vpc"]);
  assert.deepEqual(summary.unqueried_services, ["ec2", "s3"]);
  assert.deepEqual(summary.requested_services, ["vpc"]);
  assert.equal(summary.coverage.complete, false);
  assert.equal(summary.coverage.truncated, 1);
  assert.equal(summary.tools[0].pagination_complete, false);
  assert.equal(summary.tools[0].scope.vpc_id, "vpc-1");
  assert.deepEqual(summary.errors, ["QueryLimitReached"]);
  assert.equal(summary.account_id, "*********012");
  assert.equal(summary.created_at_kst, "2026-10-27 12:01:00 KST");
  assert.equal(summary.evidence, undefined);
  assert.equal(summary.tools[0].data, undefined);
});

test("history summaries redact account digits embedded in names, scopes and keys", async () => {
  const { summarizeHistoryRecord } = await import("../history.js");
  const source = record(1, { prompt: "Inspect logs123456789012", errors: ["Error123456789012"] });
  source.evidence[0].scope["key123456789012tail"] = "logs123456789012";
  const original = structuredClone(source);
  const summary = summarizeHistoryRecord(source, settings);
  assert.doesNotMatch(JSON.stringify(summary), /123456789012/);
  assert.match(summary.prompt, /logs\*{9}012/);
  assert.equal(summary.tools[0].scope["key*********012tail"], "logs*********012");
  assert.deepEqual(source, original);
});

test("scope validation supports proved legacy records and scoped failed records", async () => {
  const { validateHistoryRecord, summarizeHistoryRecord } = await import("../history.js");
  const legacy = record(); delete legacy.account_id; delete legacy.target_region; delete legacy.app_region;
  assert.equal(validateHistoryRecord(legacy, settings).id, id(1));
  const failed = record(2, { evidence: [], errors: ["RuntimeUnavailable"], status: "failed" });
  assert.equal(validateHistoryRecord(failed, settings).id, id(2));
  assert.equal(summarizeHistoryRecord(failed, settings).coverage.complete, false);
  delete failed.account_id; delete failed.target_region;
  assert.throws(() => validateHistoryRecord(failed, settings), /HistoryScopeUnverified/);
});

test("stored record scope mismatches cannot enter or leave a store", async () => {
  const store = new MemoryStore(settings);
  for (const value of [
    record(1, { account_id: "999988887777" }), record(1, { target_region: "us-east-1" }),
    record(1, { mode: "sample" }), record(1, { id: "../../foreign" }),
    record(1, { evidence: [{ ...record().evidence[0], account_id: "999988887777" }] }),
    record(1, { evidence: [{ ...record().evidence[0], region: "us-east-1" }] }),
  ]) await assert.rejects(store.put(value), /History(Account|Region|Mode)Mismatch|InvalidRunId/);
  const blocked = record(2, { status: "failed", errors: ["RuntimeAccountMismatch"],
    evidence: [{ ...record().evidence[0], account_id: "999988887777", status: "account_mismatch",
      resource_count: 0, data: [], api_calls: [{ service: "sts", api: "GetCallerIdentity",
        region: "us-east-1", success: true }] }] });
  await store.put(blocked);
  const summary = (await store.list()).runs[0];
  assert.deepEqual(summary.queried_services, []);
  assert.equal(summary.coverage.complete, false);
  assert.doesNotMatch(JSON.stringify(summary), /999988887777|123456789012/);
});

test("S3 writes original records and separate indexes and lists only the fixed scope", async () => {
  const fake = fakeS3(), store = new S3Store(settings, fake.client);
  await store.put(record(1)); await store.put(record(3)); await store.put(record(2));
  assert.equal(fake.objects.size, 6);
  assert.equal(JSON.parse(fake.objects.get(`runs/${id(1)}.json`)).account_id, settings.accountId);
  for (const call of fake.calls.filter((c) => c.type === "PutObjectCommand")) {
    assert.equal(call.ServerSideEncryption, "AES256");
    assert.equal(call.ExpectedBucketOwner, settings.accountId);
  }
  const page = await store.list({ limit: 2 });
  assert.deepEqual(page.runs.map((r) => r.id), [id(3), id(2)]);
  assert.deepEqual((await store.list({ limit: 2, cursor: page.next_cursor })).runs.map((r) => r.id), [id(1)]);
  for (const call of fake.calls.filter((c) => c.type === "ListObjectsV2Command")) {
    assert.equal(call.Prefix, "history/123456789012/ap-northeast-2/");
    assert.ok(call.MaxKeys <= 20);
    assert.equal(call.ExpectedBucketOwner, settings.accountId);
  }
  assert.doesNotMatch(JSON.stringify(page.runs), /123456789012|evidence-only-value/);
});

test("S3 history rejects another bucket or mode cursor before querying S3", async () => {
  const fake = fakeS3(), store = new S3Store(settings, fake.client);
  await store.put(record(1)); await store.put(record(2));
  const first = await store.list({ limit: 1 });
  for (const otherSettings of [
    { ...settings, stateBucket: "other-history" }, { ...settings, mode: "sample" },
  ]) {
    let calls = 0;
    const otherStore = new S3Store(otherSettings, { async send() {
      calls++; return { Contents: [], IsTruncated: false };
    } });
    await assert.rejects(otherStore.list({ cursor: first.next_cursor }), /InvalidHistoryCursor/);
    assert.equal(calls, 0);
  }
});

test("history failures are surfaced and never represented as empty history", async () => {
  const denied = Object.assign(new Error("denied"), { name: "AccessDenied" });
  const store = new S3Store(settings, { async send() { throw denied; } });
  await assert.rejects(store.list(), (error) => error === denied);
  await assert.rejects(store.get(id(1)), (error) => error === denied);
  const fake = fakeS3(), valid = new S3Store(settings, fake.client);
  assert.equal(await valid.get(id(1)), null);
  fake.objects.set(`runs/${id(1)}.json`, JSON.stringify(record(1, { account_id: "999988887777" })));
  await assert.rejects(valid.get(id(1)), /HistoryAccountMismatch/);
  await valid.put(record(2));
  const indexKey = [...fake.objects.keys()].find((key) => key.startsWith("history/"));
  const index = JSON.parse(fake.objects.get(indexKey)); index.target_region = "us-east-1";
  fake.objects.set(indexKey, JSON.stringify(index));
  await assert.rejects(valid.list(), /HistoryRegionMismatch/);
});

test("denied missing reports use an exact one-object owner-checked absence probe", async () => {
  const calls = [], denied = Object.assign(new Error("denied"), { name: "AccessDenied" });
  const store = new S3Store(settings, { async send(command) {
    calls.push({ type: command.constructor.name, ...command.input });
    if (command.constructor.name === "GetObjectCommand") throw denied;
    return { IsTruncated: false, KeyCount: 0 };
  } });
  assert.equal(await store.get(id(1)), null);
  assert.deepEqual(calls[1], {
    type: "ListObjectsV2Command", Bucket: settings.stateBucket, Prefix: `runs/${id(1)}.json`,
    MaxKeys: 1, ExpectedBucketOwner: settings.accountId,
  });
});

test("denied existing reports and unproved absence keep the original access error", async () => {
  const key = `runs/${id(1)}.json`;
  const denied = Object.assign(new Error("denied"), { name: "AccessDenied", $metadata: { httpStatusCode: 403 } });
  for (const response of [
    { Contents: [{ Key: key }], IsTruncated: false },
    { Contents: [], IsTruncated: true },
    { Contents: [] },
    { Contents: null, IsTruncated: false },
    { Contents: [{ Key: "runs/unrelated.json" }], IsTruncated: false },
    { Contents: [{ Key: key + ".a" }, { Key: key + ".b" }], IsTruncated: false },
    { Contents: [], IsTruncated: false, KeyCount: 1 },
    { Contents: [], IsTruncated: false, NextContinuationToken: "unexamined" },
    { Contents: [], IsTruncated: false, ContinuationToken: "unexpected-page" },
    { Contents: [], IsTruncated: false, StartAfter: key },
    { Contents: [], IsTruncated: false, Prefix: "foreign/" },
    { Contents: [], IsTruncated: false, CommonPrefixes: [{ Prefix: key }] },
    new Error("probe transport failure"),
  ]) {
    const store = new S3Store(settings, { async send(command) {
      if (command.constructor.name === "GetObjectCommand") throw denied;
      if (response instanceof Error) throw response;
      return response;
    } });
    await assert.rejects(store.get(id(1)), (actual) => actual === denied);
  }
});

test("report absence probes support exact-prefix siblings and never run for unsafe IDs or non-403 errors", async () => {
  const calls = [], key = `runs/${id(1)}.json`;
  const forbidden = Object.assign(new Error("forbidden"), { $metadata: { httpStatusCode: 403 } });
  const store = new S3Store(settings, { async send(command) {
    calls.push(command);
    if (command.constructor.name === "GetObjectCommand") throw forbidden;
    return { Contents: [{ Key: key + ".backup" }], IsTruncated: false, KeyCount: 1 };
  } });
  assert.equal(await store.get(id(1)), null);
  calls.length = 0;
  await assert.rejects(store.get("../private"), /InvalidRunId/);
  assert.equal(calls.length, 0);
  const unavailable = Object.assign(new Error("unavailable"), { $metadata: { httpStatusCode: 500 } });
  const broken = new S3Store(settings, { async send(command) { calls.push(command); throw unavailable; } });
  await assert.rejects(broken.get(id(1)), (actual) => actual === unavailable);
  assert.equal(calls.length, 1);
});

test("an index write failure preserves the original record and remains observable", async () => {
  const fake = fakeS3(), send = fake.client.send.bind(fake.client);
  fake.client.send = async (command) => {
    if (command.constructor.name === "PutObjectCommand" && command.input.Key.startsWith("history/")) {
      throw new Error("IndexWriteFailed");
    }
    return send(command);
  };
  const store = new S3Store(settings, fake.client);
  await assert.rejects(store.put(record()), (error) => {
    assert.equal(error.name, "HistoryIndexWriteFailed");
    assert.equal(error.code, "HistoryIndexWriteFailed");
    assert.equal(error.recordSaved, true);
    assert.equal(error.cause.message, "IndexWriteFailed");
    return true;
  });
  assert.equal(JSON.parse(fake.objects.get(`runs/${id(1)}.json`)).answer, "Saved answer");
});

test("scope includes observed CloudWatch metrics without calling VPC APIs EC2 inventory", async () => {
  const { reportServiceScope } = await import("../history.js");
  const value = record();
  value.evidence.push({ ...record().evidence[0], service: "lambda", tool: "get_resource_metrics",
    api_calls: [{ service: "cloudwatch", api: "GetMetricData", region: settings.targetRegion, success: true }] });
  const scope = reportServiceScope(value);
  assert.deepEqual(scope.queried_services, ["cloudwatch", "lambda", "vpc"]);
  assert.deepEqual(scope.unqueried_services, ["ec2", "s3"]);
});

test("corrupt pagination and missing history objects fail instead of claiming completeness", async () => {
  for (const page of [{ Contents: [], IsTruncated: true }, { Contents: [] },
    { Contents: [{ Key: "runs/foreign.json" }], IsTruncated: false }]) {
    const store = new S3Store(settings, { async send() { return page; } });
    await assert.rejects(store.list(), /InvalidHistoryPage/);
  }
  const fake = fakeS3(), store = new S3Store(settings, fake.client);
  await store.put(record());
  const send = fake.client.send.bind(fake.client);
  fake.client.send = async (command) => {
    if (command.constructor.name === "GetObjectCommand" && command.input.Key.startsWith("history/")) {
      throw Object.assign(new Error("disappeared"), { name: "NoSuchKey" });
    }
    return send(command);
  };
  await assert.rejects(store.list(), { name: "NoSuchKey" });
});

test("scope and record sizes remain bounded before S3 writes and during reads", async () => {
  const fake = fakeS3(), store = new S3Store(settings, fake.client);
  await assert.rejects(store.put(record(1, { answer: "x".repeat(4_000_001) })), /ReportTooLarge/);
  assert.equal(fake.calls.length, 0);
  fake.objects.set(`runs/${id(1)}.json`, JSON.stringify(record(1, { answer: "x".repeat(4_000_001) })));
  await assert.rejects(store.get(id(1)), /ReportTooLarge/);
  const source = record(2); source.evidence[0].scope.long = "z".repeat(5000);
  await store.put(source);
  const summary = (await store.list()).runs[0];
  assert.equal(summary.summary_truncated, true);
  assert.equal(summary.tools[0].scope.summary_truncated, true);
});

test("migration verifies STS first and writes indexes without rewriting original runs", async () => {
  const { migrateHistory } = await import("../history-migrate.js");
  const fake = fakeS3();
  for (let n = 1; n <= 3; n++) fake.objects.set(`runs/${id(n)}.json`, JSON.stringify(record(n)));
  const originals = [...fake.objects];
  const sts = { async send(command) {
    assert.equal(command.constructor.name, "GetCallerIdentityCommand");
    assert.equal(fake.calls.length, 0); return { Account: settings.accountId };
  } };
  const result = await migrateHistory(settings, { s3Client: fake.client, stsClient: sts, limit: 2 });
  assert.equal(result.indexed, 2); assert.equal(result.scanned, 2);
  assert.equal(result.complete, false); assert.ok(result.next_cursor);
  for (const [key, value] of originals) assert.equal(fake.objects.get(key), value);
  assert.ok(fake.calls.filter((c) => c.type === "PutObjectCommand").every((c) => c.Key.startsWith("history/")));
  assert.ok(fake.calls.filter((c) => c.type === "ListObjectsV2Command").every((c) => c.Prefix === "runs/"));
});

test("migration rejects another bucket cursor before any AWS call", async () => {
  const { migrateHistory } = await import("../history-migrate.js");
  const fake = fakeS3(), sts = { async send() { return { Account: settings.accountId }; } };
  for (const n of [1, 2]) fake.objects.set(`runs/${id(n)}.json`, JSON.stringify(record(n)));
  const first = await migrateHistory(settings, { s3Client: fake.client, stsClient: sts, limit: 1 });
  let calls = 0;
  await assert.rejects(migrateHistory({ ...settings, stateBucket: "other-history" }, {
    cursor: first.next_cursor,
    s3Client: { async send() { calls++; return { Contents: [], IsTruncated: false }; } },
    stsClient: { async send() { calls++; return { Account: settings.accountId }; } },
  }), /InvalidHistoryCursor/);
  assert.equal(calls, 0);
});

test("migration caps a run at 200 and reports unverified legacy records", async () => {
  const { migrateHistory } = await import("../history-migrate.js");
  const fake = fakeS3(), sts = { async send() { return { Account: settings.accountId }; } };
  for (let n = 1; n <= 201; n++) fake.objects.set(`runs/${id(n)}.json`, JSON.stringify(record(n)));
  const invalid = record(1, { evidence: [] }); delete invalid.account_id; delete invalid.target_region;
  fake.objects.set(`runs/${id(1)}.json`, JSON.stringify(invalid));
  const result = await migrateHistory(settings, { s3Client: fake.client, stsClient: sts });
  assert.equal(result.scanned, 200); assert.equal(result.indexed, 199);
  assert.equal(result.skipped[0].error, "HistoryScopeUnverified");
  assert.equal(result.complete, false);
  await assert.rejects(migrateHistory(settings, { s3Client: fake.client, stsClient: sts, limit: 201 }), /InvalidMigrationLimit/);
  const empty = fakeS3();
  await assert.rejects(migrateHistory(settings, { s3Client: empty.client,
    stsClient: { async send() { return { Account: "999988887777" }; } } }), /HistoryMigrationAccountMismatch/);
  assert.equal(empty.calls.length, 0);
});
