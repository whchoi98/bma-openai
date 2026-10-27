import { createHash } from "node:crypto";
import { InvestigationConflict, investigationPrefix, publicProcedure as projectProcedure,
  sanitizeInvestigationEvidence, sanitizeInvestigationSteps } from "./investigation-store.js";
import { cleanMarkdownProse } from "./presentation.js";
import { summarize } from "./reports.js";
import contract from "./contract.json" with { type: "json" };

export const INVESTIGATION_LIMITS = Object.freeze({ turns: 10, lifetimeMs: 6 * 60 * 60 * 1000, leaseMs: 45000 });
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const TERMINAL = new Set(["complete", "partial", "failed", "cancelled", "uncertain"]);
const pick = (value, keys) => Object.fromEntries(keys.filter((key) => value?.[key] !== undefined).map((key) => [key, value[key]]));
const object = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

function publicFields(value, keys) {
  if (!object(value)) throw investigationError("InvalidInvestigationRecord");
  const result = pick(value, keys);
  if (Object.values(result).some((item) => item !== null &&
      !["string", "boolean", "number"].includes(typeof item))) throw investigationError("InvalidInvestigationField");
  return result;
}

function strings(value, max = 100) {
  if (!Array.isArray(value) || value.length > max || value.some((item) => typeof item !== "string")) {
    throw investigationError("InvalidInvestigationField");
  }
  return [...value];
}

function checkScope(value, settings, required = false) {
  if (!settings) {
    if (required) throw investigationError("InvestigationSettingsRequired");
    return;
  }
  investigationPrefix(settings);
  for (const [key, expected] of Object.entries(scopeFields(settings))) {
    if ((required || value[key] !== undefined) && value[key] !== expected) {
      throw investigationError("InvestigationScopeMismatch");
    }
  }
}

function publicEvidence(value, settings) {
  if (Array.isArray(value) && value.length === 0 && !settings) return [];
  return sanitizeInvestigationEvidence(value, settings);
}

export const isTerminal = (status) => TERMINAL.has(status);
export const turnMarker = (id) => `[aws-ops-turn:${id}]`;
export const investigationMarker = (id) => `[aws-ops-investigation:${id}]`;
export const inputHash = (input) => createHash("sha256").update(JSON.stringify(input)).digest("hex");
export const scopeFields = (settings) => ({
  account_id: settings.accountId, app_region: settings.appRegion,
  target_region: settings.targetRegion, mode: settings.mode,
});
export function investigationError(code, httpStatus = 409) {
  return Object.assign(new Error(code), { code, httpStatus });
}
export function validateInvestigationId(id) {
  if (typeof id !== "string" || !UUID.test(id)) throw investigationError("InvalidInvestigationId", 422);
  return id;
}
export function validateInvestigationInput(body, creating = false) {
  const allowed = creating ? ["request_id", "procedure_id", "prompt", "language"] : ["request_id", "prompt", "language"];
  if (!body || Array.isArray(body) || typeof body !== "object" || Object.keys(body).some((key) => !allowed.includes(key))) {
    throw investigationError("InvalidInvestigationInput", 422);
  }
  validateInvestigationId(body.request_id);
  if (typeof body.prompt !== "string" || !body.prompt.trim() || body.prompt.length > 4000) {
    throw investigationError("InvalidInvestigationInput", 422);
  }
  const language = body.language ?? "ko";
  if (!["ko", "en"].includes(language)) throw investigationError("InvalidLanguage", 422);
  if (creating && typeof body.procedure_id !== "string") throw investigationError("InvalidProcedure", 422);
  return { request_id: body.request_id, ...(creating ? { procedure_id: body.procedure_id } : {}),
    prompt: body.prompt.trim(), language };
}

// Retry only a proved conditional-write conflict, never an ambiguous transport error.
export async function mutateRecord(store, kind, id, transform, attempts = 6) {
  for (let attempt = 0; attempt < attempts; attempt++) {
    const saved = await store[`get${kind}`](id);
    if (!saved) throw investigationError("InvestigationNotFound", 404);
    const next = await transform(structuredClone(saved.value));
    if (next === null || next === undefined) return null;
    try { return await store[`put${kind}`](next, saved.etag); }
    catch (error) {
      if (error.recordSaved && error.value && error.etag) {
        return { value: error.value, etag: error.etag, warning: error.code || error.message };
      }
      if (!(error instanceof InvestigationConflict) || attempt === attempts - 1) throw error;
    }
  }
  throw new InvestigationConflict();
}

export function selectTurnItems(items, runId) {
  const unique = [...new Map(items.filter((item) => item && typeof item.id === "string").map((item) => [item.id, item])).values()];
  const matches = unique.filter((item) => item.type === "message" && item.role === "user" &&
    (item.content || []).some((part) => part.type === "input_text" && typeof part.text === "string" &&
      part.text.startsWith(turnMarker(runId))));
  if (!matches.length) return null;
  if (matches.length !== 1) throw investigationError("DuplicateTurnInput");
  const turnId = matches[0].turn_id;
  if (typeof turnId !== "string" || !turnId || turnId.length > 256) throw investigationError("MissingTurnIdentity");
  return { turnId, items: unique.filter((item) => item.turn_id === turnId) };
}

export function publicProcedure(value) {
  return projectProcedure(value);
}
export function publicInvestigation(value, settings) {
  checkScope(value, settings);
  if (!Array.isArray(value.turns) || value.turns.length > INVESTIGATION_LIMITS.turns) {
    throw investigationError("InvalidInvestigationTurns");
  }
  return { ...publicFields(value, ["id", "title", "created_at", "updated_at", "status", "active_run_id", "expires_at"]),
    procedure: publicProcedure(value.procedure),
    turns: value.turns.map((turn) => publicFields(turn, ["id", "prompt", "language", "status", "created_at"])) };
}
export function publicReport(value, settings) {
  checkScope(value, settings);
  const result = publicFields(value, [
    "id", "investigation_id", "turn_index", "prompt", "language", "mode", "created_at", "account_id",
    "app_region", "target_region", "answer", "status", "model", "agent_backend", "model_processing_scope",
    "report_available", "evidence_reused",
  ]);
  if (value.procedure !== undefined) result.procedure = publicProcedure(value.procedure);
  if (value.procedure_steps !== undefined) result.procedure_steps = sanitizeInvestigationSteps(value.procedure_steps, true);
  if (value.evidence !== undefined) result.evidence = publicEvidence(value.evidence, settings);
  for (const key of ["errors", "supported_services", "source_run_ids"]) {
    if (value[key] !== undefined) result[key] = strings(value[key]);
  }
  if (result.source_run_ids) result.source_run_ids.forEach(validateInvestigationId);
  return result;
}
export function publicTurn(value, settings) {
  if (!value) return null;
  checkScope(value, settings);
  const result = publicFields(value, ["id", "investigation_id", "status", "phase", "prompt", "language", "created_at",
    "updated_at", "answer"]);
  if (value.evidence !== undefined) result.evidence = publicEvidence(value.evidence, settings);
  if (value.errors !== undefined) result.errors = strings(value.errors);
  if (value.procedure_steps !== undefined) result.procedure_steps = sanitizeInvestigationSteps(value.procedure_steps, true);
  if (value.result) {
    if (value.result.id !== value.id || value.result.investigation_id !== value.investigation_id) {
      throw investigationError("InvalidInvestigationResult");
    }
    result.result = publicReport(value.result, settings);
  }
  return result;
}

export function buildInvestigationReport(turn, session, settings, previous = null) {
  checkScope(turn, settings, true);
  checkScope(session, settings, true);
  const position = session.turns.findIndex((item) => item.id === turn.id);
  if (turn.investigation_id !== session.id || position < 0) throw investigationError("InvestigationScopeMismatch");
  const en = turn.language === "en";
  const errors = [...new Set(strings(turn.errors || []))];
  let evidence = sanitizeInvestigationEvidence(turn.evidence || [], settings);
  const stopped = ["cancelled", "uncertain", "failed"].includes(turn.status);
  if (stopped) {
    errors.push({ cancelled: "InvestigationCancelled", uncertain: "InvestigationUncertain", failed: "InvestigationFailed" }[turn.status]);
  }
  let previousIds = [];
  if (previous) {
    checkScope(previous, settings, true);
    const prior = new Set(session.turns.slice(0, position).map((item) => item.id));
    previousIds = [...new Set([previous.id, ...strings(previous.source_run_ids || [], INVESTIGATION_LIMITS.turns)])];
    if (previous.investigation_id !== session.id || previousIds.some((id) => !prior.has(id))) {
      throw investigationError("InvalidPreviousInvestigationReport");
    }
    previous = { ...previous, evidence: sanitizeInvestigationEvidence(previous.evidence || [], settings) };
  }
  const identityFailed = evidence.some((item) => item.status === "account_mismatch" ||
    item.api_calls?.some((call) => call.api === "GetCallerIdentity" && !call.success) ||
    (item.tool === "get_account_context" && item.data.some((row) => row.account_verified === false))) ||
    errors.some((error) => /AccountMismatch|IdentityVerificationFailed|EvidenceScope/.test(error));
  const resourceEvidence = (items) => items.filter((item) => item.service !== "sts");
  const reused = !stopped && !identityFailed && !errors.length && !resourceEvidence(evidence).length &&
    Boolean(previous && resourceEvidence(previous.evidence || []).length);
  if (stopped || identityFailed) previousIds = [];
  let notice = "";
  if (reused) {
    const hasCurrentContext = evidence.some((item) => item.service === "sts");
    evidence = [...evidence, ...structuredClone(previous.evidence).filter((item) => item.service !== "sts" || !hasCurrentContext)];
    const times = [...new Set(resourceEvidence(previous.evidence).map((item) => item.observed_at).filter(Boolean))].sort();
    notice = en
      ? `Previously observed evidence reused: ${times.join(", ")}. No new resource API query was made for this answer.\n\n`
      : `이전 조회 근거를 재사용했습니다: ${times.join(", ")}. 이번 답변을 위해 리소스 API를 새로 조회하지 않았습니다.\n\n`;
  }
  let answer = cleanMarkdownProse(turn.answer || "");
  if (!answer && resourceEvidence(evidence).length) {
    answer = summarize(evidence, turn.language);
    if (!errors.length) errors.push("NoFinalAssistantMessage");
  }
  if (!resourceEvidence(evidence).length) {
    if (!errors.length) errors.push("NoResourceEvidence");
    if (!answer) answer = en ? "No resource query evidence was received." : "리소스 조회 근거를 받지 못했습니다.";
  }
  if (identityFailed) answer = en ? "Query stopped because the execution account could not be verified." : "실행 계정을 확인하지 못해 조회를 중단했습니다.";
  const procedure = publicProcedure(session.procedure);
  const title = procedure.name?.[en ? "en" : "ko"] || procedure.id;
  const prefix = en ? `Procedure: ${title}, version ${procedure.version}.\n\n` : `운영 절차: ${title}, 버전 ${procedure.version}.\n\n`;
  const partial = turn.status === "partial" || errors.length || evidence.some((item) =>
    !["ok", "empty"].includes(item.status) || item.truncated === true || item.pagination_complete === false ||
    item.permission_denied === true || item.errors?.length || item.missing_resource_ids?.length ||
    item.data.some((row) => row.data_status && !["ok", "complete", "Complete", "no_data"].includes(row.data_status)));
  return {
    ...scopeFields(settings), id: turn.id, investigation_id: session.id,
    turn_index: position + 1,
    prompt: turn.prompt, language: turn.language, created_at: turn.created_at,
    answer: prefix + notice + answer, evidence, errors,
    status: turn.status === "failed" || identityFailed || !resourceEvidence(evidence).length
      ? "failed" : partial ? "partial" : "complete",
    supported_services: contract.supported_services, model: settings.mode === "live" ? settings.model : null,
    agent_backend: "bma", model_processing_scope: "app_region",
    procedure, procedure_steps: sanitizeInvestigationSteps(turn.procedure_steps || [], true),
    evidence_reused: reused, source_run_ids: previousIds, report_available: true,
    ...(session.bma_session_id ? { bma_session_id: session.bma_session_id } : {}),
  };
}
