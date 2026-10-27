import { createHash, randomUUID } from "node:crypto";
import { S3Client, GetObjectCommand, PutObjectCommand, ListObjectsV2Command } from "@aws-sdk/client-s3";
import { LIMITS, validId, error, publicJob } from "./config.js";

const MAX_JSON = 4_000_000, MAX_TIME = 9_999_999_999_999;
export const sha256 = (value) => createHash("sha256").update(value).digest("hex");
export class Conflict extends Error {
  constructor() { super("StateConflict"); this.code = "StateConflict"; this.httpStatus = 409; }
}
export async function readBody(body, maximum) {
  const chunks = []; let size = 0;
  for await (const part of body) {
    const chunk = Buffer.isBuffer(part) ? part : Buffer.from(part);
    size += chunk.length;
    if (size > maximum) { body.destroy?.(); throw error("FileTooLarge", 413); }
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}
const indexKey = (value) => `index/${String(MAX_TIME - Date.parse(value.created_at)).padStart(13, "0")}-${validId(value.id)}.json`;
const validKey = (key) => /^(?:uploads\/[a-f0-9-]{36}\/(?:data|meta\.json)|jobs\/[a-f0-9-]{36}\/(?:input\.json|state\.json|artifacts\.json|outputs\/[A-Za-z0-9_.-]{1,120})|index\/\d{13}-[a-f0-9-]{36}\.json)$/.test(key);

export class StudioStore {
  constructor(settings, client) {
    this.settings = settings;
    this.client = client || new S3Client({ region: settings.appRegion, maxAttempts: 3,
      requestHandler: { requestTimeout: 15000, connectionTimeout: 3000 } });
  }
  params(key) {
    if (!validKey(key) || key.includes("..")) throw error("InvalidObjectKey");
    return { Bucket: this.settings.bucket, ExpectedBucketOwner: this.settings.accountId, Key: key };
  }
  async get(key, maximum = MAX_JSON) {
    let response;
    try { response = await this.client.send(new GetObjectCommand(this.params(key))); }
    catch (cause) {
      if (cause.name === "NoSuchKey") return null;
      if (cause.name === "AccessDenied" || cause.$metadata?.httpStatusCode === 403) {
        try {
          const probe = await this.client.send(new ListObjectsV2Command({
            Bucket: this.settings.bucket, ExpectedBucketOwner: this.settings.accountId, Prefix: key, MaxKeys: 1,
          }));
          const rows = probe.Contents || [];
          if (probe.IsTruncated === false && rows.length <= 1 && !probe.NextContinuationToken &&
              rows.every((row) => typeof row.Key === "string" && row.Key.startsWith(key)) &&
              !rows.some((row) => row.Key === key)) return null;
        } catch { /* A failed probe does not turn an access error into absence. */ }
      }
      throw cause;
    }
    if (response.ContentLength > maximum) { response.Body?.destroy?.(); throw error("FileTooLarge", 413); }
    return { bytes: await readBody(response.Body, maximum), etag: response.ETag };
  }
  async json(key) {
    const raw = await this.get(key);
    if (!raw) return null;
    let value;
    try { value = JSON.parse(raw.bytes); } catch { throw error("InvalidStoredData", 503); }
    if (!value || Array.isArray(value) || value.account_id !== this.settings.accountId || value.app_region !== this.settings.appRegion) {
      throw error("StoredScopeMismatch", 503);
    }
    if (typeof raw.etag !== "string" || !raw.etag || /[\r\n*]/.test(raw.etag)) throw error("InvalidStateVersion", 503);
    return { value, etag: raw.etag };
  }
  async put(key, bytes, mime, etag) {
    const params = { ...this.params(key), Body: bytes, ContentType: mime, ServerSideEncryption: "AES256" };
    if (etag === null) params.IfNoneMatch = "*";
    else {
      if (typeof etag !== "string" || !etag || /[\r\n*]/.test(etag)) throw error("InvalidStateVersion");
      params.IfMatch = etag;
    }
    try { return await this.client.send(new PutObjectCommand(params)); }
    catch (cause) { if ([409, 412].includes(cause.$metadata?.httpStatusCode)) throw new Conflict(); throw cause; }
  }
  async putJson(key, value, etag) {
    const bytes = Buffer.from(JSON.stringify(value));
    if (bytes.length > MAX_JSON) throw error("StateTooLarge", 413);
    const response = await this.put(key, bytes, "application/json", etag);
    return { value: structuredClone(value), etag: response.ETag };
  }
  scope() { return { account_id: this.settings.accountId, app_region: this.settings.appRegion }; }
  async upload(name, bytes) {
    if (!bytes.length || bytes.length > LIMITS.fileBytes) throw error("FileTooLarge", 413);
    const id = randomUUID();
    const value = { ...this.scope(), id, name, size: bytes.length,
      extension: name.split(".").at(-1).toLowerCase(), sha256: sha256(bytes), created_at: new Date().toISOString() };
    await this.put(`uploads/${id}/data`, bytes, "application/octet-stream", null);
    await this.putJson(`uploads/${id}/meta.json`, value, null);
    return value;
  }
  async owned(key, id, field = "id") {
    const saved = await this.json(key);
    if (saved && saved.value[field] !== id) throw error("StoredScopeMismatch", 503);
    return saved;
  }
  uploadMeta(id) { return this.owned(`uploads/${validId(id)}/meta.json`, id); }
  input(id) { return this.owned(`jobs/${validId(id)}/input.json`, id); }
  state(id) { return this.owned(`jobs/${validId(id)}/state.json`, id); }
  artifacts(id) { return this.owned(`jobs/${validId(id)}/artifacts.json`, id, "job_id"); }
  async create(input) {
    let saved;
    try { saved = await this.putJson(`jobs/${validId(input.id)}/input.json`, input, null); }
    catch (cause) {
      if (!(cause instanceof Conflict)) throw cause;
      saved = await this.input(input.id);
      if (!saved || saved.value.input_hash !== input.input_hash) throw error("RequestIdConflict", 409);
    }
    input = saved.value;
    let state = await this.state(input.id);
    if (!state) {
      const value = { ...this.scope(), id: input.id, title: input.prompt.slice(0, 100),
        prompt: input.prompt, created_at: input.created_at, updated_at: input.created_at,
        deadline_at: new Date(Date.parse(input.created_at) + LIMITS.turnSeconds * 1000).toISOString(),
        style: input.style, language: input.language, outputs: input.outputs, source_job_id: input.source_job_id,
        upload: input.upload ? { id: input.upload.id, name: input.upload.name, size: input.upload.size } : null,
        status: "queued", phase: "queued", completed_steps: [], answer: "", artifacts: [], warnings: [], errors: [] };
      try { state = await this.putJson(`jobs/${input.id}/state.json`, value, null); }
      catch (cause) { if (!(cause instanceof Conflict)) throw cause; state = await this.state(input.id); }
    }
    await this.index(state.value);
    return state;
  }
  async update(id, transform) {
    for (let attempt = 0; attempt < 6; attempt++) {
      const saved = await this.state(id);
      if (!saved) throw error("JobNotFound", 404);
      const next = await transform(structuredClone(saved.value));
      if (!next) return null;
      if (["id", "created_at", "prompt", "style", "language", "outputs", "upload", "source_job_id"].some(
        (field) => JSON.stringify(next[field]) !== JSON.stringify(saved.value[field]))) throw error("ImmutableJobField");
      try { return await this.putJson(`jobs/${id}/state.json`, next, saved.etag); }
      catch (cause) { if (!(cause instanceof Conflict) || attempt === 5) throw cause; }
    }
    throw new Conflict();
  }
  async index(value) {
    const key = indexKey(value);
    for (let attempt = 0; attempt < 4; attempt++) {
      const previous = await this.json(key);
      const current = await this.state(value.id);
      if (!current || indexKey(current.value) !== key) throw error("InvalidListResult", 503);
      try {
        return await this.putJson(key, { ...this.scope(), ...publicJob(current.value), profile: undefined,
          artifacts: undefined, answer: undefined }, previous?.etag ?? null);
      } catch (cause) { if (!(cause instanceof Conflict) || attempt === 3) throw cause; }
    }
  }
  async list({ limit = 10, cursor } = {}) {
    if (!Number.isInteger(limit) || limit < 1 || limit > 20) throw error("InvalidListLimit");
    let token;
    if (cursor) {
      try {
        if (cursor.length > 4096) throw new Error();
        const decoded = JSON.parse(Buffer.from(cursor, "base64url"));
        if (decoded.scope !== sha256(this.settings.bucket + this.settings.accountId) ||
            typeof decoded.token !== "string" || !decoded.token) throw new Error();
        token = decoded.token;
      } catch { throw error("InvalidCursor"); }
    }
    const page = await this.client.send(new ListObjectsV2Command({
      Bucket: this.settings.bucket, ExpectedBucketOwner: this.settings.accountId,
      Prefix: "index/", MaxKeys: limit, ...(token ? { ContinuationToken: token } : {}),
    }));
    if (typeof page.IsTruncated !== "boolean" || (page.Contents || []).length > limit ||
        (page.IsTruncated && (!page.NextContinuationToken || page.NextContinuationToken === token))) throw error("InvalidListResult", 503);
    const jobs = [];
    for (const item of page.Contents || []) {
      if (!/^index\/\d{13}-[a-f0-9-]{36}\.json$/.test(item.Key)) throw error("InvalidListResult", 503);
      const saved = await this.json(item.Key);
      if (!saved || indexKey(saved.value) !== item.Key) throw error("InvalidListResult", 503);
      jobs.push(publicJob(saved.value));
    }
    return { jobs, complete: !page.IsTruncated, next_cursor: page.IsTruncated
      ? Buffer.from(JSON.stringify({ scope: sha256(this.settings.bucket + this.settings.accountId), token: page.NextContinuationToken })).toString("base64url") : null };
  }
}
