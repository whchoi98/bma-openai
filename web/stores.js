import { S3Client, PutObjectCommand, GetObjectCommand, ListObjectsV2Command } from "@aws-sdk/client-s3";
import { HISTORY_LIMITS, createHistoryIndex, decodeHistoryCursor, encodeHistoryCursor,
  historyIndexKey, historyPageLimit, historyPrefix, isHistoryIndexKey, summarizeHistoryRecord,
  validateHistoryIndex, validateHistoryRecord, validateRunId } from "./history.js";

const sampleSettings = { mode: "sample", accountId: "000000000000", appRegion: "us-east-1", targetRegion: "ap-northeast-2" };

function jsonBody(value, maxBytes) {
  const body = JSON.stringify(value);
  if (Buffer.byteLength(body) > maxBytes) throw new Error("ReportTooLarge");
  return body;
}

async function readJson(response, maxBytes) {
  const chunks = [];
  let size = 0;
  for await (const chunk of response.Body) {
    const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += bytes.length;
    if (size > maxBytes) { response.Body.destroy?.(); throw new Error("ReportTooLarge"); }
    chunks.push(bytes);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

async function proveObjectAbsent(client, scope, key) {
  try {
    const page = await client.send(new ListObjectsV2Command({ ...scope, Prefix: key, MaxKeys: 1 }));
    const objects = page?.Contents === undefined ? [] : page.Contents;
    return page !== null && typeof page === "object" && !Array.isArray(page) &&
      page.IsTruncated === false && Array.isArray(objects) && objects.length <= 1 &&
      (page.Prefix === undefined || page.Prefix === key) &&
      (page.Name === undefined || page.Name === scope.Bucket) &&
      (page.MaxKeys === undefined || page.MaxKeys === 1) &&
      (page.KeyCount === undefined || page.KeyCount === objects.length) &&
      (page.$metadata?.httpStatusCode === undefined || page.$metadata.httpStatusCode === 200) &&
      page.NextContinuationToken === undefined && page.ContinuationToken === undefined && page.StartAfter === undefined &&
      (page.CommonPrefixes === undefined || (Array.isArray(page.CommonPrefixes) && page.CommonPrefixes.length === 0)) &&
      objects.every((item) => item !== null && typeof item === "object" && !Array.isArray(item) &&
        typeof item.Key === "string" && item.Key.startsWith(key) && item.Key !== key);
  } catch { return false; }
}

export class MemoryStore {
  constructor(settings = sampleSettings) {
    historyPrefix(settings);
    this.settings = { ...settings }; this.records = new Map();
  }
  async put(record) {
    validateHistoryRecord(record, this.settings);
    jsonBody(record, HISTORY_LIMITS.recordBytes);
    this.records.set(record.id, structuredClone(record));
    while (this.records.size > 20) this.records.delete(this.records.keys().next().value);
  }
  async get(id) {
    validateRunId(id);
    const record = this.records.get(id);
    return record ? structuredClone(validateHistoryRecord(record, this.settings)) : null;
  }
  async list({ limit = 10, cursor } = {}) {
    historyPageLimit(limit);
    const after = decodeHistoryCursor("memory", cursor, this.settings);
    const prefix = historyPrefix(this.settings);
    if (after && !isHistoryIndexKey(prefix + after, this.settings)) throw new Error("InvalidHistoryCursor");
    const all = [...this.records.values()].map((record) => ({
      key: historyIndexKey(record, this.settings).slice(prefix.length), record,
    })).sort((a, b) => a.key.localeCompare(b.key)).filter((item) => !after || item.key > after);
    const selected = all.slice(0, limit), complete = all.length <= limit;
    return {
      runs: selected.map(({ record }) => summarizeHistoryRecord(record, this.settings)),
      next_cursor: complete ? null : encodeHistoryCursor("memory", selected.at(-1).key, this.settings), complete,
    };
  }
}

export class S3Store {
  constructor(settings, client = new S3Client({ region: settings.appRegion, maxAttempts: 3,
    requestHandler: { requestTimeout: 10000, connectionTimeout: 3000 } })) {
    historyPrefix(settings);
    this.settings = { ...settings }; this.bucket = settings.stateBucket; this.client = client;
    this.owner = settings.accountId;
  }
  async put(record) {
    validateHistoryRecord(record, this.settings);
    const body = jsonBody(record, HISTORY_LIMITS.recordBytes);
    // Validate and size the index before writing either object.
    const index = jsonBody(createHistoryIndex(record, this.settings), HISTORY_LIMITS.indexBytes);
    await this.client.send(new PutObjectCommand({ Bucket: this.bucket, Key: `runs/${record.id}.json`, Body: body,
      ExpectedBucketOwner: this.owner, ContentType: "application/json", ServerSideEncryption: "AES256" }));
    try { await this.putIndex(record, index); }
    catch (cause) {
      throw Object.assign(new Error("HistoryIndexWriteFailed", { cause }), {
        name: "HistoryIndexWriteFailed", code: "HistoryIndexWriteFailed", recordSaved: true,
      });
    }
  }
  async putIndex(record, body) {
    await this.client.send(new PutObjectCommand({ Bucket: this.bucket, Key: historyIndexKey(record, this.settings), Body: body,
      ExpectedBucketOwner: this.owner, ContentType: "application/json", ServerSideEncryption: "AES256" }));
  }
  async writeHistoryIndex(record) {
    const body = jsonBody(createHistoryIndex(record, this.settings), HISTORY_LIMITS.indexBytes);
    await this.putIndex(record, body);
  }
  async get(id) {
    validateRunId(id);
    const key = `runs/${id}.json`;
    let response;
    try { response = await this.client.send(new GetObjectCommand({ Bucket: this.bucket, Key: key,
      ExpectedBucketOwner: this.owner })); }
    catch (error) {
      if (error.name === "NoSuchKey") return null;
      if ((error.name === "AccessDenied" || error.$metadata?.httpStatusCode === 403) &&
          await proveObjectAbsent(this.client, { Bucket: this.bucket, ExpectedBucketOwner: this.owner }, key)) return null;
      throw error;
    }
    const record = validateHistoryRecord(await readJson(response, HISTORY_LIMITS.recordBytes), this.settings);
    if (record.id !== id) throw new Error("InvalidHistoryRecord");
    return record;
  }
  async list({ limit = 10, cursor } = {}) {
    historyPageLimit(limit);
    const token = decodeHistoryCursor("s3", cursor, this.settings);
    const page = await this.client.send(new ListObjectsV2Command({
      Bucket: this.bucket, Prefix: historyPrefix(this.settings), MaxKeys: limit, ExpectedBucketOwner: this.owner,
      ...(token ? { ContinuationToken: token } : {}),
    }));
    const objects = page.Contents || [];
    if (typeof page.IsTruncated !== "boolean" || !Array.isArray(objects) || objects.length > limit ||
        objects.some((item) => !isHistoryIndexKey(item.Key, this.settings)) ||
        (page.IsTruncated && (!page.NextContinuationToken || page.NextContinuationToken === token))) {
      throw new Error("InvalidHistoryPage");
    }
    const runs = await Promise.all(objects.map(async ({ Key }) => {
      const response = await this.client.send(new GetObjectCommand({
        Bucket: this.bucket, Key, ExpectedBucketOwner: this.owner,
      }));
      return validateHistoryIndex(await readJson(response, HISTORY_LIMITS.indexBytes), Key, this.settings);
    }));
    const complete = page.IsTruncated !== true;
    return { runs, next_cursor: complete ? null : encodeHistoryCursor("s3", page.NextContinuationToken, this.settings), complete };
  }
}
