import { createHash } from "node:crypto";
import { cleanMarkdownProse, displayAccountId, maskAccountIds } from "./presentation.js";

export const HISTORY_LIMITS = Object.freeze({ page: 20, recordBytes: 4_000_000, indexBytes: 128_000 });
const LEGACY_SERVICES = ["ec2", "rds", "ecs", "lambda", "cloudwatch"];
const RUN_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const MAX_TIME = 9_999_999_999_999;
const object = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const count = (value) => Number.isInteger(value) && value >= 0 ? value : null;
const serviceList = (values) => [...new Set((Array.isArray(values) ? values : [])
  .filter((value) => typeof value === "string" && /^[a-z][a-z0-9_-]{0,39}$/.test(value)))].sort();

export function validateRunId(id) {
  if (typeof id !== "string" || !RUN_ID.test(id)) throw new Error("InvalidRunId");
  return id;
}

export function historyPrefix(settings) {
  if (!/^\d{12}$/.test(settings?.accountId || "")) throw new Error("InvalidHistoryAccount");
  if (settings.appRegion !== "us-east-1" || settings.targetRegion !== "ap-northeast-2") {
    throw new Error("InvalidHistoryRegion");
  }
  return `history/${settings.accountId}/${settings.targetRegion}/`;
}

function timestamp(value) {
  const time = typeof value === "string" && /^\d{4}-\d{2}-\d{2}T[\d:.]+Z$/.test(value) ? Date.parse(value) : NaN;
  if (!Number.isFinite(time) || time < 0 || time > MAX_TIME) throw new Error("InvalidHistoryTimestamp");
  return time;
}

export function historyIndexKey(record, settings) {
  const prefix = historyPrefix(settings);
  return `${prefix}${String(MAX_TIME - timestamp(record.created_at)).padStart(13, "0")}-${validateRunId(record.id)}.json`;
}

export function isHistoryIndexKey(key, settings) {
  const prefix = historyPrefix(settings);
  return typeof key === "string" && key.startsWith(prefix) &&
    /^\d{13}-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.json$/.test(key.slice(prefix.length));
}

export function historyTimeKst(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Unknown" : new Intl.DateTimeFormat("sv-SE",
    { timeZone: "Asia/Seoul", dateStyle: "short", timeStyle: "medium" }).format(date) + " KST";
}

export function validateHistoryRecord(record, settings) {
  historyPrefix(settings);
  if (!object(record)) throw new Error("InvalidHistoryRecord");
  validateRunId(record.id); timestamp(record.created_at);
  if (!["sample", "live"].includes(record.mode) || (settings.mode && record.mode !== settings.mode)) {
    throw new Error("HistoryModeMismatch");
  }
  if (record.account_id !== undefined && record.account_id !== settings.accountId) throw new Error("HistoryAccountMismatch");
  for (const key of ["target_region", "region"]) {
    if (record[key] !== undefined && record[key] !== settings.targetRegion) throw new Error("HistoryRegionMismatch");
  }
  if (record.app_region !== undefined && record.app_region !== settings.appRegion) throw new Error("HistoryRegionMismatch");
  if (!Array.isArray(record.evidence) || record.evidence.length > 100 ||
      (record.errors !== undefined && (!Array.isArray(record.errors) || record.errors.length > 100))) {
    throw new Error("InvalidHistoryRecord");
  }
  const trustedScope = record.account_id === settings.accountId && record.target_region === settings.targetRegion;
  let provedScope = false;
  for (const result of record.evidence) {
    if (!object(result) || !Array.isArray(result.data) || !Array.isArray(result.api_calls)) {
      throw new Error("InvalidHistoryRecord");
    }
    if (result.region !== settings.targetRegion) throw new Error("HistoryRegionMismatch");
    if (result.mode !== undefined && result.mode !== record.mode) throw new Error("HistoryModeMismatch");
    const blocked = trustedScope && result.data.length === 0 &&
      (result.status === "account_mismatch" || (result.account_id == null &&
        result.api_calls.some((call) => call.api === "GetCallerIdentity" && call.success === false))) &&
      !result.api_calls.some((call) => call.service !== "sts" && call.success === true);
    if (result.account_id !== settings.accountId && !blocked) throw new Error("HistoryAccountMismatch");
    if (result.account_id === settings.accountId) provedScope = true;
    for (const row of result.data) {
      if (!object(row)) throw new Error("InvalidHistoryRecord");
      if (row.account_id !== undefined && row.account_id !== settings.accountId) throw new Error("HistoryAccountMismatch");
      for (const key of ["region", "target_region"]) {
        if (row[key] !== undefined && row[key] !== settings.targetRegion) throw new Error("HistoryRegionMismatch");
      }
    }
    for (const call of result.api_calls) {
      if (!object(call) || (call.region !== undefined && call.region !== settings.targetRegion &&
          !(call.service === "sts" && call.region === settings.appRegion))) throw new Error("HistoryRegionMismatch");
    }
  }
  if (!trustedScope && !provedScope) throw new Error("HistoryScopeUnverified");
  return record;
}

// Share the already saved query scope with history and Office exports. SDK service
// names (for example ec2 for VPC) must not replace the displayed resource service.
export function reportServiceScope(record) {
  const context = (record.evidence || []).find((item) => item.tool === "get_account_context")?.data?.[0];
  const declared = record.supported_services || context?.supported_services;
  const supported = serviceList(declared || LEGACY_SERVICES);
  const queried = serviceList((record.evidence || [])
    .filter((item) => item.service !== "sts" && item.api_calls?.some((call) => call.service !== "sts"))
    .flatMap((item) => [item.service, ...(item.api_calls.some((call) => call.service === "cloudwatch") ? ["cloudwatch"] : [])]));
  return {
    supported_services: supported,
    requested_services: serviceList(record.requested_services),
    queried_services: queried,
    unqueried_services: supported.filter((service) => !queried.includes(service)),
    scope_source: declared ? "saved" : "legacy_supported_services",
  };
}

export function reportCoverage(record) {
  const tools = (record.evidence || []).filter((item) => item.service !== "sts");
  return {
    tool_results: (record.evidence || []).length, resource_tool_results: tools.length,
    completed: tools.filter((item) => item.status === "ok").length,
    empty: tools.filter((item) => item.status === "empty").length,
    partial: tools.filter((item) => item.status === "partial").length,
    access_denied: tools.filter((item) => item.status === "access_denied").length,
    failed: tools.filter((item) => !["ok", "empty", "partial", "access_denied"].includes(item.status)).length,
    truncated: tools.filter((item) => item.truncated === true).length,
    pagination_incomplete: tools.filter((item) => item.pagination_complete !== true).length,
    complete: tools.length > 0 && record.status === "complete" && !(record.errors || []).length &&
      tools.every((item) => ["ok", "empty"].includes(item.status) && item.pagination_complete === true && item.truncated === false),
  };
}

// Collect identities from structured identity fields and ARNs, including blocked
// account evidence. Caller-supplied IDs cover failed reports with no evidence.
export function reportAccountIds(record, accountIds = []) {
  const ids = new Set(accountIds.filter((value) => typeof value === "string" && /^\d{12}$/.test(value)));
  const walk = (value, key = "", depth = 0) => {
    if (depth > 30) throw new Error("InvalidHistoryRecord");
    if ((typeof value === "string" || typeof value === "number") &&
        /(?:^|_)(?:account_?id|owner_?id)$/i.test(key) && /^\d{12}$/.test(String(value))) ids.add(String(value));
    if (typeof value === "string") {
      for (const match of value.matchAll(/arn:[a-z0-9-]+:[a-z0-9-]+:[a-z0-9-]*:(\d{12}):/g)) ids.add(match[1]);
    } else if (Array.isArray(value)) value.forEach((item) => walk(item, key, depth + 1));
    else if (object(value)) for (const [name, item] of Object.entries(value)) walk(item, name, depth + 1);
  };
  walk(record);
  return [...ids];
}

export function redactReportValue(value, accounts, options = {}) {
  if (typeof value === "string") return maskAccountIds(value, accounts, options);
  if (typeof value === "number" && accounts.includes(String(value))) return maskAccountIds(String(value), accounts, options);
  if (Array.isArray(value)) return value.map((item) => redactReportValue(item, accounts, options));
  if (object(value)) return Object.fromEntries(Object.entries(value)
    .map(([key, item]) => [maskAccountIds(key, accounts, options), redactReportValue(item, accounts, options)]));
  return value;
}

export function summarizeHistoryRecord(record, settings) {
  validateHistoryRecord(record, settings);
  const accounts = reportAccountIds(record, [settings.accountId]);
  const prompt = maskAccountIds(cleanMarkdownProse(record.prompt || ""), accounts, { partial: true, strict: true });
  let scopeTruncated = false;
  const tools = record.evidence.map((item) => {
    let scope = item.scope || {};
    if (Buffer.byteLength(JSON.stringify(scope)) > 4096) {
      scope = { summary_truncated: true, reason: "ScopeTooLarge" }; scopeTruncated = true;
    }
    return {
      service: item.service, tool: item.tool, status: item.status,
      resource_count: ["ok", "empty", "partial"].includes(item.status) ? count(item.resource_count) : null,
      pagination_complete: item.pagination_complete === true, truncated: item.truncated === true,
      permission_denied: item.permission_denied === true, scope,
    };
  });
  const result = {
    id: record.id, created_at: record.created_at, created_at_kst: historyTimeKst(record.created_at),
    account_id: displayAccountId(settings.accountId), app_region: settings.appRegion, target_region: settings.targetRegion,
    mode: record.mode, language: record.language === "en" ? "en" : "ko",
    status: record.status || "failed", report_available: record.report_available !== false,
    prompt: prompt.slice(0, 320), prompt_truncated: prompt.length > 320,
    ...reportServiceScope(record), coverage: reportCoverage(record), tools, errors: record.errors || [],
    summary_truncated: prompt.length > 320 || scopeTruncated,
  };
  // This validated UUID is an opaque routing key, not an AWS identity field.
  return { ...redactReportValue(result, accounts, { partial: true, strict: true }), id: record.id };
}

export function createHistoryIndex(record, settings) {
  return { schema_version: 1, account_id: settings.accountId, target_region: settings.targetRegion,
    summary: summarizeHistoryRecord(record, settings) };
}

export function validateHistoryIndex(index, key, settings) {
  if (!object(index) || index.schema_version !== 1 || !object(index.summary)) throw new Error("InvalidHistoryIndex");
  if (index.account_id !== settings.accountId) throw new Error("HistoryAccountMismatch");
  if (index.target_region !== settings.targetRegion) throw new Error("HistoryRegionMismatch");
  const summary = index.summary;
  if (historyIndexKey(summary, settings) !== key ||
      summary.account_id !== displayAccountId(settings.accountId) || summary.target_region !== settings.targetRegion ||
      summary.app_region !== settings.appRegion || (settings.mode && summary.mode !== settings.mode) ||
      !object(summary.coverage) || !Array.isArray(summary.tools) || summary.tools.length > 100) {
    throw new Error("InvalidHistoryIndex");
  }
  // Never pass unexpected index payload fields (such as full evidence) to clients.
  const keys = ["id", "created_at", "created_at_kst", "account_id", "app_region", "target_region", "mode",
    "language", "status", "report_available", "prompt", "prompt_truncated", "supported_services",
    "requested_services", "queried_services", "unqueried_services", "scope_source", "coverage", "tools",
    "errors", "summary_truncated"];
  if (Object.keys(summary).some((name) => !keys.includes(name)) ||
      summary.tools.some((tool) => !object(tool) || Object.keys(tool).some((name) => ![
        "service", "tool", "status", "resource_count", "pagination_complete", "truncated", "permission_denied", "scope",
      ].includes(name)))) throw new Error("InvalidHistoryIndex");
  return { ...redactReportValue(summary, reportAccountIds(summary, [settings.accountId]),
    { partial: true, strict: true }), id: summary.id };
}

export function historyPageLimit(limit = 10) {
  if (!Number.isInteger(limit) || limit < 1 || limit > HISTORY_LIMITS.page) throw new Error("InvalidHistoryLimit");
  return limit;
}

function scopeHash(kind, settings) {
  const scope = [kind, historyPrefix(settings), settings.appRegion, settings.mode || null];
  if (kind !== "memory") scope.push(settings.stateBucket || null);
  return createHash("sha256").update(JSON.stringify(scope)).digest("hex").slice(0, 24);
}

export function encodeHistoryCursor(kind, token, settings) {
  if (typeof token !== "string" || !token || token.length > 2048) throw new Error("InvalidHistoryCursor");
  return Buffer.from(JSON.stringify({ version: 1, kind, scope: scopeHash(kind, settings), token })).toString("base64url");
}

export function decodeHistoryCursor(kind, cursor, settings) {
  if (cursor === undefined || cursor === null || cursor === "") return undefined;
  try {
    if (typeof cursor !== "string" || cursor.length > 4096 || !/^[A-Za-z0-9_-]+$/.test(cursor)) throw new Error();
    const value = JSON.parse(Buffer.from(cursor, "base64url").toString("utf8"));
    if (value.version !== 1 || value.kind !== kind || value.scope !== scopeHash(kind, settings) ||
        typeof value.token !== "string" || !value.token || value.token.length > 2048) throw new Error();
    return value.token;
  } catch { throw new Error("InvalidHistoryCursor"); }
}
