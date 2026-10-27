import { once } from "node:events";
import { validateInvestigationId, validateInvestigationInput } from "./investigation-records.js";

const errors = Object.freeze({
  RequestTooLarge: 413, InvalidJson: 400, InvalidInvestigationRequest: 400,
  InvalidInvestigationLimit: 400, InvalidInvestigationCursor: 400,
  InvalidInvestigationId: 422, InvalidInvestigationInput: 422, InvalidLanguage: 422,
  InvalidProcedure: 422, UnknownProcedure: 422, MethodNotAllowed: 405, NotFound: 404,
  InvestigationNotFound: 404, InvestigationConflict: 409, InvestigationActive: 409,
  InvestigationBusy: 409, InvestigationExpired: 409, InvestigationTurnLimit: 409,
  InvestigationUnavailable: 503, InvestigationDispatchFailed: 503, InvestigationReadFailed: 503,
  InvestigationIndexWriteFailed: 503, AccountMismatch: 409, AccountVerificationFailed: 503,
  InvestigationsUnavailable: 503, RequestIdConflict: 409, WorkerDispatchFailed: 503,
  InvestigationConfigurationChanged: 409, InvalidInvestigationRecord: 503,
});
const safeStatuses = new Set([400, 401, 403, 404, 405, 409, 410, 413, 422, 429, 500, 503]);
const routeError = (code) => Object.assign(new Error(code), { code, httpStatus: errors[code] });

export function publicInvestigationError(error) {
  const code = typeof error?.code === "string" ? error.code : error?.message;
  if (!Object.hasOwn(errors, code)) return { code: "InvestigationUnavailable", status: 503 };
  return { code, status: safeStatuses.has(error?.httpStatus) ? error.httpStatus : errors[code] };
}

async function readJson(req) {
  let size = 0;
  const chunks = [];
  // Leaving this iterator must not destroy the response socket before a 413 is sent.
  for await (const chunk of req.iterator({ destroyOnReturn: false })) {
    const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += bytes.length;
    if (size > 16_384) {
      req.resume();
      throw routeError("RequestTooLarge");
    }
    chunks.push(bytes);
  }
  let body;
  try { body = JSON.parse(Buffer.concat(chunks).toString("utf8")); }
  catch { throw routeError("InvalidJson"); }
  if (!body || Array.isArray(body) || typeof body !== "object") throw routeError("InvalidInvestigationInput");
  return body;
}

function validateQuery(url, list = false) {
  const seen = new Set();
  for (const [key] of url.searchParams) {
    if (!list || !["limit", "cursor"].includes(key) || seen.has(key)) throw routeError("InvalidInvestigationRequest");
    seen.add(key);
  }
  if (!list) return;
  const limit = url.searchParams.get("limit") ?? "10";
  if (!/^\d+$/.test(limit) || Number(limit) < 1 || Number(limit) > 20) throw routeError("InvalidInvestigationLimit");
  const cursor = url.searchParams.get("cursor");
  if (cursor !== null && (!cursor || cursor.length > 4096 || !/^[A-Za-z0-9_-]+$/.test(cursor))) {
    throw routeError("InvalidInvestigationCursor");
  }
  return { limit: Number(limit), ...(cursor === null ? {} : { cursor }) };
}

function allowedMethod(req, res, allowed) {
  if (allowed.includes(req.method)) return;
  res.setHeader("allow", allowed.join(", "));
  throw routeError("MethodNotAllowed");
}

async function streamEvents(service, id, runId, req, res, responseHeaders) {
  const controller = new AbortController();
  const disconnected = () => { if (!res.writableEnded) controller.abort(); };
  res.on("close", disconnected);
  let iterator;
  try {
    iterator = service.stream(id, runId, { signal: controller.signal })[Symbol.asyncIterator]();
    let current = await iterator.next();
    if (controller.signal.aborted) return;
    res.writeHead(200, { ...responseHeaders, "content-type": "text/event-stream; charset=utf-8", "x-accel-buffering": "no" });
    while (!current.done && !controller.signal.aborted) {
      let event = current.value;
      if (event?.type === "error") event = { type: "error", code: publicInvestigationError(event).code };
      if (!["snapshot", "complete", "heartbeat", "error"].includes(event?.type)) throw routeError("InvestigationUnavailable");
      if (!res.write(`data: ${JSON.stringify(event)}\n\n`)) await once(res, "drain", { signal: controller.signal });
      current = await iterator.next();
    }
  } catch (error) {
    if (controller.signal.aborted || res.destroyed) return;
    if (!res.headersSent) throw error;
    res.write(`data: ${JSON.stringify({ type: "error", code: publicInvestigationError(error).code })}\n\n`);
  } finally {
    controller.abort();
    res.off("close", disconnected);
    await iterator?.return?.();
    if (res.headersSent && !res.destroyed) res.end();
  }
}

export function createInvestigationRoutes({ service, verifyAccount, json, responseHeaders = {} }) {
  return async function investigationRoutes(req, res, url) {
    const path = url.pathname;
    if (path !== "/api/procedures" && !path.startsWith("/api/procedures/") &&
        path !== "/api/investigations" && !path.startsWith("/api/investigations/")) return false;
    try {
      await verifyAccount();
      if (path === "/api/procedures") {
        allowedMethod(req, res, ["GET"]);
        validateQuery(url);
        json(res, 200, await service.catalog());
        return true;
      }
      if (path === "/api/investigations") {
        allowedMethod(req, res, ["GET", "POST"]);
        if (req.method === "GET") json(res, 200, await service.list(validateQuery(url, true)));
        else {
          validateQuery(url);
          json(res, 202, await service.create(validateInvestigationInput(await readJson(req), true)));
        }
        return true;
      }
      const match = /^\/api\/investigations\/([^/]+)(\/turns(?:\/([^/]+)(?:\/(events|cancel))?)?)?$/.exec(path);
      if (!match) throw routeError("NotFound");
      const [, id, turns, runId, action] = match;
      validateInvestigationId(id);
      if (runId !== undefined) validateInvestigationId(runId);
      validateQuery(url);
      if (!turns) {
        allowedMethod(req, res, ["GET"]);
        json(res, 200, await service.get(id));
      } else if (!runId) {
        allowedMethod(req, res, ["POST"]);
        json(res, 202, await service.submit(id, validateInvestigationInput(await readJson(req))));
      } else if (!action) {
        allowedMethod(req, res, ["GET"]);
        json(res, 200, await service.get(id, runId));
      } else if (action === "cancel") {
        allowedMethod(req, res, ["POST"]);
        if (Object.keys(await readJson(req)).length) throw routeError("InvalidInvestigationInput");
        json(res, 202, await service.cancel(id, runId));
      } else {
        allowedMethod(req, res, ["GET"]);
        await streamEvents(service, id, runId, req, res, responseHeaders);
      }
    } catch (error) {
      const visible = publicInvestigationError(error);
      if (!res.headersSent && !res.destroyed) json(res, visible.status, { error: visible.code });
      else if (!res.destroyed) res.end();
    }
    return true;
  };
}
