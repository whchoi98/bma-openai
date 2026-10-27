import { createHash, randomUUID } from "node:crypto";
import { GetObjectCommand, ListObjectsV2Command, PutObjectCommand, S3Client } from "@aws-sdk/client-s3";
import { maskAccountIds } from "./presentation.js";
import { sanitizeResult } from "./evidence.js";
import contract from "./contract.json" with { type: "json" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const MAX_TIME = 9_999_999_999_999;
const LIMITS = { sessions: 128 * 1024, turns: 4_000_000, index: 128 * 1024 };
const STATUSES = new Set(["queued", "running", "complete", "partial", "failed", "cancelled", "uncertain"]);
const SUMMARY_KEYS = ["id", "title", "created_at", "updated_at", "status", "procedure", "turns",
  "active_run_id", "expires_at"];
const PROCEDURE_KEYS = ["id", "version", "sha256", "name", "description", "steps"];
const STEP_KEYS = ["id", "label", "tools"];
const TURN_KEYS = ["id", "prompt", "language", "status", "created_at"];
const object = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const pick = (value, keys) => Object.fromEntries(keys.filter((key) => value[key] !== undefined)
  .map((key) => [key, value[key]]));
const clone = (value) => structuredClone(value);
const canonical = (value) => JSON.stringify(value, (_, item) => object(item)
  ? Object.fromEntries(Object.keys(item).sort().map((key) => [key, item[key]])) : item);

function scalar(value) {
  if (value !== null && !["string", "number", "boolean"].includes(typeof value)) {
    throw new Error("InvalidInvestigationField");
  }
  if (typeof value === "number" && !Number.isFinite(value)) throw new Error("InvalidInvestigationField");
  return value;
}

function strings(value, max = 100) {
  if (!Array.isArray(value) || value.length > max || value.some((item) => typeof item !== "string")) {
    throw new Error("InvalidInvestigationField");
  }
  return [...value];
}

function project(value, keys, nested = {}) {
  if (!object(value)) throw new Error("InvalidInvestigationField");
  return Object.fromEntries(keys.filter((key) => value[key] !== undefined)
    .map((key) => [key, nested[key] ? nested[key](value[key]) : scalar(value[key])]));
}

function rows(value, keys, max) {
  if (!Array.isArray(value) || value.length > max) throw new Error("InvalidInvestigationField");
  return value.map((item) => project(item, keys));
}

const DATA_NESTED = {
  points: (value) => rows(value, ["timestamp", "value"], 1440),
  deployments: (value) => rows(value, ["id", "status", "rollout_state", "desired_count", "running_count",
    "pending_count", "created_at", "updated_at"], 10),
  security_checks: (value) => rows(value, ["id", "status", "severity"], 20),
  ingress_rules: (value) => rows(value, ["protocol", "from_port", "to_port", "source_type", "source", "unrestricted"], 50),
  ...Object.fromEntries(["subnet_ids", "security_group_ids", "attached_instance_ids", "supported_services",
    "encryption_algorithms"].map((key) => [key, (value) => strings(value)])),
};
const SCOPE_KEYS = ["max_resources", "max_pages", "max_api_calls", "requested_resource_ids", "cluster",
  "function_kind", "alarm_state", "vpc_id", "kind_coverage", "omitted_kinds", "truncated_kinds",
  "max_ingress_rules", "max_relationships", "resource_id", "namespace", "dimensions", "start_time",
  "end_time", "period_seconds", "max_datapoints", "resource_existence"];
const SCOPE_NESTED = {
  requested_resource_ids: (value) => strings(value),
  omitted_kinds: (value) => strings(value),
  truncated_kinds: (value) => strings(value),
  dimensions: (value) => rows(value, ["Name", "Value"], 30),
  kind_coverage: (value) => project(value, ["vpc", "subnet", "route_table", "security_group",
    "internet_gateway", "nat_gateway", "vpc_endpoint"]),
};

/** Normalize persisted/HTTP evidence without carrying raw model item fields. */
export function sanitizeInvestigationEvidence(evidence, settings, { retainItemIds = false } = {}) {
  if (!settings) throw new Error("InvestigationSettingsRequired");
  investigationPrefix(settings);
  if (!Array.isArray(evidence) || evidence.length > 100) throw new Error("InvalidInvestigationEvidence");
  return evidence.map((value) => {
    if (!object(value) || !contract.tools.includes(value.tool)) throw new Error("InvalidInvestigationEvidence");
    let approved;
    try { approved = sanitizeResult(value, settings, value.tool); }
    catch (error) {
      if (error instanceof TypeError) throw new Error("InvalidInvestigationEvidence", { cause: error });
      throw error;
    }
    const clean = project(approved, contract.top_fields, {
      data: (data) => data.map((row) => project(row, contract.data_fields, DATA_NESTED)),
      api_calls: (calls) => rows(calls, ["service", "api", "region", "success", "duration_ms", "request_id", "retry_attempts"], 31),
      errors: (errors) => rows(errors, ["code", "service", "api", "kind", "resource_id"], 100),
      notes: (notes) => strings(notes),
      resource_ids: (ids) => strings(ids),
      missing_resource_ids: (ids) => strings(ids),
      scope: (scope) => project(scope, SCOPE_KEYS, SCOPE_NESTED),
    });
    for (const row of clean.data) {
      if (row.account_id !== undefined && row.account_id !== settings.accountId) throw new Error("EvidenceAccountMismatch");
      if (["region", "target_region"].some((key) => row[key] !== undefined && row[key] !== settings.targetRegion) ||
          (row.app_region !== undefined && row.app_region !== settings.appRegion)) throw new Error("EvidenceRegionMismatch");
    }
    for (const call of clean.api_calls) {
      if (call.region !== undefined && call.region !== settings.targetRegion &&
          !(call.service === "sts" && call.region === settings.appRegion)) throw new Error("EvidenceRegionMismatch");
    }
    if (clean.account_id !== settings.accountId && clean.api_calls.some((call) => call.service !== "sts" && call.success)) {
      throw new Error("EvidenceAccountMismatch");
    }
    if (retainItemIds && value.item_id !== undefined) {
      if (typeof value.item_id !== "string" || !value.item_id || value.item_id.length > 256) {
        throw new Error("InvalidInvestigationItemId");
      }
      clean.item_id = value.item_id;
    }
    return clean;
  });
}

export function sanitizeInvestigationSteps(value, withStatus = false) {
  if (!Array.isArray(value) || value.length > 20) throw new Error("InvalidInvestigationProcedure");
  return value.map((step) => {
    const clean = project(step, withStatus ? [...STEP_KEYS, "status"] : STEP_KEYS, {
      label: (label) => project(label, ["ko", "en"]),
      tools: (tools) => strings(tools),
    });
    stringFields(clean, ["id", "status"]);
    if (clean.label) stringFields(clean.label, ["ko", "en"]);
    if (clean.tools?.some((tool) => !contract.tools.includes(tool))) throw new Error("InvalidInvestigationProcedure");
    if (clean.status !== undefined && !["pending", "running", "complete", "partial", "failed", "not_requested"].includes(clean.status)) {
      throw new Error("InvalidInvestigationProcedure");
    }
    return clean;
  });
}

export class InvestigationConflict extends Error {
  constructor(cause) {
    super("InvestigationConflict", cause ? { cause } : undefined);
    this.name = "InvestigationConflict";
    this.code = "InvestigationConflict";
    this.statusCode = 409;
  }
}

export function investigationPrefix(settings) {
  if (!/^\d{12}$/.test(settings?.accountId || "")) throw new Error("InvalidInvestigationAccount");
  if (settings.appRegion !== "us-east-1" || settings.targetRegion !== "ap-northeast-2") {
    throw new Error("InvalidInvestigationRegion");
  }
  if (!["sample", "live"].includes(settings.mode)) throw new Error("InvalidInvestigationMode");
  return `investigations/${settings.accountId}/${settings.targetRegion}/`;
}

function validateId(id) {
  if (typeof id !== "string" || !UUID.test(id)) throw new Error("InvalidInvestigationId");
  return id;
}

function timestamp(value) {
  const time = typeof value === "string" && /^\d{4}-\d\d-\d\dT[\d:.]+Z$/.test(value) ? Date.parse(value) : NaN;
  if (!Number.isFinite(time) || time < 0 || time > MAX_TIME) throw new Error("InvalidInvestigationTimestamp");
  return time;
}

function validateETag(etag) {
  if (typeof etag !== "string" || !etag.trim() || etag.length > 256 || /[*,\x00-\x20\x7f]/.test(etag)) {
    throw new Error("InvalidInvestigationETag");
  }
  return etag;
}

function validateScope(value, settings) {
  if (!object(value)) throw new Error("InvalidInvestigationRecord");
  if (value.account_id !== settings.accountId) throw new Error("InvestigationAccountMismatch");
  if (value.app_region !== settings.appRegion || value.target_region !== settings.targetRegion ||
      (value.region !== undefined && value.region !== settings.targetRegion)) {
    throw new Error("InvestigationRegionMismatch");
  }
  if (value.mode !== settings.mode) throw new Error("InvestigationModeMismatch");
}

function stringFields(value, keys) {
  for (const key of keys) {
    if (value[key] !== undefined && typeof value[key] !== "string") throw new Error("InvalidInvestigationField");
  }
}

function validatePublicReferences(value) {
  validateId(value.id); timestamp(value.created_at);
  stringFields(value, ["title", "prompt", "language"]);
  if (value.language !== undefined && !["ko", "en"].includes(value.language)) throw new Error("InvalidInvestigationLanguage");
  for (const key of ["updated_at", "expires_at"]) {
    if (value[key] !== undefined) timestamp(value[key]);
  }
  if (value.status !== undefined && !STATUSES.has(value.status)) throw new Error("InvalidInvestigationStatus");
  if (value.active_run_id != null) validateId(value.active_run_id);
  if (value.turns !== undefined) {
    if (!Array.isArray(value.turns) || value.turns.length > 10) throw new Error("InvalidInvestigationTurns");
    for (const turn of value.turns) {
      if (!object(turn)) throw new Error("InvalidInvestigationTurn");
      validateId(turn.id);
      stringFields(turn, ["prompt", "language"]);
      if (turn.language !== undefined && !["ko", "en"].includes(turn.language)) throw new Error("InvalidInvestigationLanguage");
      if (turn.created_at !== undefined) timestamp(turn.created_at);
      if (turn.status !== undefined && !STATUSES.has(turn.status)) throw new Error("InvalidInvestigationStatus");
    }
  }
}

function validateRecord(value, kind, settings) {
  validateScope(value, settings);
  validatePublicReferences(value);
  if (kind === "turns") validateId(value.investigation_id);
  stringFields(value, ["answer", "phase", "bma_session_id", "bma_turn_id"]);
  const normalized = { ...value };
  if (value.procedure !== undefined) publicProcedure(value.procedure);
  if (value.errors !== undefined) normalized.errors = strings(value.errors);
  if (value.evidence !== undefined) {
    normalized.evidence = sanitizeInvestigationEvidence(value.evidence, settings, { retainItemIds: true });
  }
  if (value.procedure_steps !== undefined) normalized.procedure_steps = sanitizeInvestigationSteps(value.procedure_steps, true);
  if (value.result != null) {
    if (!object(value.result) || value.result.id !== value.id || value.result.investigation_id !== value.investigation_id) {
      throw new Error("InvalidInvestigationResult");
    }
    if (value.result.result !== undefined) throw new Error("InvalidInvestigationResult");
    normalized.result = validateRecord(value.result, "turns", settings);
    if (normalized.result.procedure !== undefined) normalized.result.procedure = publicProcedure(normalized.result.procedure);
  }
  return normalized;
}

function jsonBody(value, maxBytes) {
  const body = JSON.stringify(value);
  if (typeof body !== "string") throw new Error("InvalidInvestigationRecord");
  if (Buffer.byteLength(body) > maxBytes) throw new Error("InvestigationTooLarge");
  return body;
}

async function readJson(response, maxBytes) {
  if (response.ContentLength > maxBytes) {
    response.Body?.destroy?.();
    throw new Error("InvestigationTooLarge");
  }
  const chunks = [];
  let size = 0;
  for await (const chunk of response.Body) {
    const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += bytes.length;
    if (size > maxBytes) {
      response.Body.destroy?.();
      throw new Error("InvestigationTooLarge");
    }
    chunks.push(bytes);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

export function publicProcedure(procedure) {
  if (procedure == null) return procedure;
  if (!object(procedure)) throw new Error("InvalidInvestigationProcedure");
  const result = pick(procedure, PROCEDURE_KEYS);
  stringFields(result, ["id", "version", "sha256"]);
  for (const key of ["name", "description"]) {
    if (result[key] !== undefined) {
      if (!object(result[key])) throw new Error("InvalidInvestigationProcedure");
      result[key] = pick(result[key], ["ko", "en"]);
      stringFields(result[key], ["ko", "en"]);
    }
  }
  if (result.steps !== undefined) {
    result.steps = sanitizeInvestigationSteps(result.steps);
  }
  return result;
}

function maskText(value, settings) {
  if (typeof value === "string") return maskAccountIds(value, [settings.accountId], { partial: true, strict: true });
  if (Array.isArray(value)) return value.map((item) => maskText(item, settings));
  if (object(value)) return Object.fromEntries(Object.entries(value)
    .map(([key, item]) => [key, maskText(item, settings)]));
  return value;
}

function summary(value, settings) {
  const selected = pick(value, SUMMARY_KEYS);
  if (selected.procedure !== undefined) selected.procedure = publicProcedure(selected.procedure);
  if (selected.turns !== undefined) selected.turns = selected.turns.map((turn) => pick(turn, TURN_KEYS));
  const result = maskText(selected, settings);
  // Opaque UUIDs can contain the sample account's twelve zeroes.
  result.id = value.id;
  if (value.active_run_id !== undefined) result.active_run_id = value.active_run_id;
  if (result.turns) result.turns.forEach((turn, i) => { turn.id = value.turns[i].id; });
  return result;
}

function indexKey(value, settings) {
  return `${investigationPrefix(settings)}index/${String(MAX_TIME - timestamp(value.created_at)).padStart(13, "0")}-${validateId(value.id)}.json`;
}

function validIndexKey(key, settings) {
  const prefix = investigationPrefix(settings) + "index/";
  return typeof key === "string" && key.startsWith(prefix) &&
    /^\d{13}-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.json$/.test(key.slice(prefix.length));
}

function validStorageKey(key, settings) {
  if (validIndexKey(key, settings)) return true;
  const prefix = investigationPrefix(settings);
  if (typeof key !== "string" || !key.startsWith(prefix)) return false;
  const match = /^(?:sessions|turns)\/([^/]+)\.json$/.exec(key.slice(prefix.length));
  return Boolean(match && UUID.test(match[1]));
}

async function proveObjectAbsent(client, scope, key) {
  try {
    const page = await client.send(new ListObjectsV2Command({ ...scope, Prefix: key, MaxKeys: 1 }));
    const objects = page?.Contents === undefined ? [] : page.Contents;
    return object(page) && page.IsTruncated === false && Array.isArray(objects) && objects.length <= 1 &&
      (page.Prefix === undefined || page.Prefix === key) &&
      (page.Name === undefined || page.Name === scope.Bucket) &&
      (page.MaxKeys === undefined || page.MaxKeys === 1) &&
      (page.KeyCount === undefined || page.KeyCount === objects.length) &&
      (page.$metadata?.httpStatusCode === undefined || page.$metadata.httpStatusCode === 200) &&
      page.NextContinuationToken === undefined && page.ContinuationToken === undefined && page.StartAfter === undefined &&
      (page.CommonPrefixes === undefined || (Array.isArray(page.CommonPrefixes) && page.CommonPrefixes.length === 0)) &&
      objects.every((item) => object(item) && typeof item.Key === "string" && item.Key.startsWith(key) && item.Key !== key);
  } catch { return false; }
}

function createIndex(value, settings) {
  return { schema_version: 1, account_id: settings.accountId, app_region: settings.appRegion,
    target_region: settings.targetRegion, mode: settings.mode, summary: summary(value, settings) };
}

function onlyKeys(value, keys) {
  if (!object(value) || Object.keys(value).some((key) => !keys.includes(key))) {
    throw new Error("InvalidInvestigationIndex");
  }
}

function validateIndex(value, key, settings) {
  validateScope(value, settings);
  onlyKeys(value, ["schema_version", "account_id", "app_region", "target_region", "mode", "summary"]);
  if (value.schema_version !== 1 || !object(value.summary)) throw new Error("InvalidInvestigationIndex");
  const item = value.summary;
  validatePublicReferences(item);
  if (indexKey(item, settings) !== key) throw new Error("InvalidInvestigationIndex");
  onlyKeys(item, SUMMARY_KEYS);
  if (item.procedure != null) {
    onlyKeys(item.procedure, PROCEDURE_KEYS);
    for (const field of ["name", "description"]) {
      if (item.procedure[field] !== undefined) onlyKeys(item.procedure[field], ["ko", "en"]);
    }
    if (item.procedure.steps !== undefined) {
      if (!Array.isArray(item.procedure.steps)) throw new Error("InvalidInvestigationIndex");
      for (const step of item.procedure.steps) {
        onlyKeys(step, STEP_KEYS);
        if (step.label !== undefined) onlyKeys(step.label, ["ko", "en"]);
      }
    }
  }
  for (const turn of item.turns || []) onlyKeys(turn, TURN_KEYS);
  return summary(item, settings);
}

function checkImmutable(previous, next, kind) {
  if (previous.created_at !== next.created_at ||
      (kind === "turns" && previous.investigation_id !== next.investigation_id) ||
      (kind === "sessions" && (previous.expires_at !== next.expires_at ||
        canonical(previous.procedure) !== canonical(next.procedure) ||
        (previous.bma_session_id != null && previous.bma_session_id !== next.bma_session_id)))) {
    throw new Error("ImmutableInvestigationField");
  }
}

function pageLimit(limit) {
  if (!Number.isInteger(limit) || limit < 1 || limit > 20) throw new Error("InvalidInvestigationLimit");
}

function scopeHash(kind, settings) {
  return createHash("sha256").update(JSON.stringify([kind, investigationPrefix(settings),
    settings.appRegion, settings.mode, settings.stateBucket || null])).digest("hex").slice(0, 24);
}

function encodeCursor(kind, token, settings) {
  if (typeof token !== "string" || !token || token.length > 2048) throw new Error("InvalidInvestigationCursor");
  return Buffer.from(JSON.stringify({ version: 1, kind, scope: scopeHash(kind, settings), token })).toString("base64url");
}

function decodeCursor(kind, cursor, settings) {
  if (cursor === undefined || cursor === null || cursor === "") return undefined;
  try {
    if (typeof cursor !== "string" || cursor.length > 4096 || !/^[A-Za-z0-9_-]+$/.test(cursor)) throw new Error();
    const value = JSON.parse(Buffer.from(cursor, "base64url").toString("utf8"));
    if (!object(value) || value.version !== 1 || value.kind !== kind || value.scope !== scopeHash(kind, settings) ||
        typeof value.token !== "string" || !value.token || value.token.length > 2048) throw new Error();
    return value.token;
  } catch { throw new Error("InvalidInvestigationCursor"); }
}

function prepared(value, kind, settings) {
  const normalized = validateRecord(JSON.parse(jsonBody(value, LIMITS[kind])), kind, settings);
  const body = jsonBody(normalized, LIMITS[kind]);
  // Validate the complete index before committing the session.
  if (kind === "sessions") jsonBody(createIndex(normalized, settings), LIMITS.index);
  return { body, value: normalized };
}

export class MemoryInvestigationStore {
  constructor(settings) {
    investigationPrefix(settings);
    this.settings = Object.freeze({ ...settings });
    this.sessions = new Map();
    this.turns = new Map();
  }
  async getSession(id) { return this.get("sessions", id); }
  async getTurn(id) { return this.get("turns", id); }
  async createSession(value) { return this.write("sessions", value); }
  async createTurn(value) { return this.write("turns", value); }
  async putSession(value, etag) { validateETag(etag); return this.write("sessions", value, etag); }
  async putTurn(value, etag) { validateETag(etag); return this.write("turns", value, etag); }
  get(kind, id) {
    const saved = this[kind].get(validateId(id));
    if (!saved) return null;
    return clone({ ...saved, value: validateRecord(saved.value, kind, this.settings) });
  }
  write(kind, value, etag) {
    const data = prepared(value, kind, this.settings), previous = this[kind].get(value.id);
    if (etag === undefined ? previous !== undefined : previous?.etag !== etag) throw new InvestigationConflict();
    if (previous) checkImmutable(previous.value, data.value, kind);
    const saved = { value: data.value, etag: `"${randomUUID()}"` };
    this[kind].set(value.id, saved);
    return clone(saved);
  }
  async list({ limit = 10, cursor } = {}) {
    pageLimit(limit);
    const after = decodeCursor("memory", cursor, this.settings);
    if (after && !validIndexKey(after, this.settings)) throw new Error("InvalidInvestigationCursor");
    const all = [...this.sessions.values()].map(({ value }) => ({
      key: indexKey(validateRecord(value, "sessions", this.settings), this.settings), value,
    })).sort((a, b) => a.key.localeCompare(b.key)).filter((item) => !after || item.key > after);
    const selected = all.slice(0, limit), complete = all.length <= limit;
    return { investigations: selected.map(({ value }) => summary(value, this.settings)),
      next_cursor: complete ? null : encodeCursor("memory", selected.at(-1).key, this.settings), complete };
  }
}

export class S3InvestigationStore {
  constructor(settings, client) {
    investigationPrefix(settings);
    if (typeof settings.stateBucket !== "string" || !settings.stateBucket) throw new Error("InvalidInvestigationBucket");
    this.settings = Object.freeze({ ...settings });
    this.client = client || new S3Client({ region: settings.appRegion, maxAttempts: 3,
      requestHandler: { requestTimeout: 10000, connectionTimeout: 3000 } });
  }
  params(Key) {
    return { Bucket: this.settings.stateBucket, ExpectedBucketOwner: this.settings.accountId, Key };
  }
  key(kind, id) { return `${investigationPrefix(this.settings)}${kind}/${validateId(id)}.json`; }
  async getSession(id) { return this.get("sessions", id); }
  async getTurn(id) { return this.get("turns", id); }
  async createSession(value) { return this.write("sessions", value); }
  async createTurn(value) { return this.write("turns", value); }
  async putSession(value, etag) { validateETag(etag); return this.write("sessions", value, etag); }
  async putTurn(value, etag) { validateETag(etag); return this.write("turns", value, etag); }
  async read(key, limit) {
    if (!validStorageKey(key, this.settings)) throw new Error("InvalidInvestigationKey");
    let response;
    try { response = await this.client.send(new GetObjectCommand(this.params(key))); }
    catch (error) {
      if (error.name === "NoSuchKey" &&
          (error.$metadata?.httpStatusCode === undefined || error.$metadata.httpStatusCode === 404)) return null;
      if ((error.name === "AccessDenied" || error.$metadata?.httpStatusCode === 403) &&
          await proveObjectAbsent(this.client, {
            Bucket: this.settings.stateBucket, ExpectedBucketOwner: this.settings.accountId,
          }, key)) return null;
      throw error;
    }
    return { value: await readJson(response, limit), etag: validateETag(response.ETag) };
  }
  async get(kind, id) {
    const saved = await this.read(this.key(kind, id), LIMITS[kind]);
    if (!saved) return null;
    saved.value = validateRecord(saved.value, kind, this.settings);
    if (saved.value.id !== id) throw new Error("InvalidInvestigationRecord");
    return saved;
  }
  async conditionalPut(key, body, etag) {
    try {
      return await this.client.send(new PutObjectCommand({
        ...this.params(key), Body: body, ContentType: "application/json", ServerSideEncryption: "AES256",
        ...(etag === undefined ? { IfNoneMatch: "*" } : { IfMatch: validateETag(etag) }),
      }));
    } catch (cause) {
      if ([409, 412].includes(cause.$metadata?.httpStatusCode)) throw new InvestigationConflict(cause);
      throw cause;
    }
  }
  async write(kind, value, etag) {
    const data = prepared(value, kind, this.settings);
    if (etag !== undefined) {
      const previous = await this.get(kind, value.id);
      if (!previous || previous.etag !== etag) throw new InvestigationConflict();
      checkImmutable(previous.value, data.value, kind);
    }
    const response = await this.conditionalPut(this.key(kind, data.value.id), data.body, etag);
    const saved = { value: data.value, etag: response.ETag };
    try { validateETag(saved.etag); }
    catch (cause) {
      throw Object.assign(new Error("InvestigationWriteReceiptInvalid", { cause }),
        { name: "InvestigationWriteReceiptInvalid", code: "InvestigationWriteReceiptInvalid",
          recordSaved: true, ...saved });
    }
    if (kind === "sessions") {
      try { await this.writeIndex(data.value); }
      catch (cause) {
        throw Object.assign(new Error("InvestigationIndexWriteFailed", { cause }),
          { name: "InvestigationIndexWriteFailed", code: "InvestigationIndexWriteFailed", recordSaved: true, ...saved });
      }
    }
    return saved;
  }
  async writeIndex(value) {
    const key = indexKey(value, this.settings);
    for (let attempt = 0; attempt < 4; attempt++) {
      const previous = await this.read(key, LIMITS.index);
      if (previous) validateIndex(previous.value, key, this.settings);
      // Read after the index ETag: if a newer writer wins the index meanwhile,
      // If-Match fails and the next attempt refreshes the current session.
      const current = await this.getSession(value.id);
      if (!current || indexKey(current.value, this.settings) !== key) throw new Error("InvalidInvestigationIndex");
      const body = jsonBody(createIndex(current.value, this.settings), LIMITS.index);
      try {
        await this.conditionalPut(key, body, previous?.etag);
        return;
      } catch (cause) {
        if (!(cause instanceof InvestigationConflict) || attempt === 3) throw cause;
      }
    }
  }
  async list({ limit = 10, cursor } = {}) {
    pageLimit(limit);
    const token = decodeCursor("s3", cursor, this.settings);
    const page = await this.client.send(new ListObjectsV2Command({
      Bucket: this.settings.stateBucket, ExpectedBucketOwner: this.settings.accountId,
      Prefix: investigationPrefix(this.settings) + "index/", MaxKeys: limit,
      ...(token ? { ContinuationToken: token } : {}),
    }));
    const objects = page.Contents || [];
    if (typeof page.IsTruncated !== "boolean" || !Array.isArray(objects) || objects.length > limit ||
        objects.some((item) => !validIndexKey(item?.Key, this.settings)) ||
        (page.IsTruncated && (!objects.length || typeof page.NextContinuationToken !== "string" ||
          !page.NextContinuationToken || page.NextContinuationToken === token))) throw new Error("InvalidInvestigationPage");
    const investigations = await Promise.all(objects.map(async ({ Key }) => {
      const saved = await this.read(Key, LIMITS.index);
      if (!saved) throw new Error("InvestigationIndexMissing");
      return validateIndex(saved.value, Key, this.settings);
    }));
    const complete = !page.IsTruncated;
    return { investigations, next_cursor: complete ? null : encodeCursor("s3", page.NextContinuationToken, this.settings), complete };
  }
}
