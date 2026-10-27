import http from "node:http";
import { randomUUID, timingSafeEqual } from "node:crypto";
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { STSClient, GetCallerIdentityCommand } from "@aws-sdk/client-sts";
import { SampleRunner, LiveRunner } from "./runners.js";
import { ConverseRunner } from "./converse.js";
import { MemoryStore, S3Store } from "./stores.js";
import { renderHtml, renderMarkdown } from "./reports.js";
import { redactReportValue, reportAccountIds, validateHistoryRecord } from "./history.js";
import { OFFICE_MIME, renderOfficeReport } from "./office-reports.js";
import { InvestigationService } from "./investigations.js";
import { createInvestigationRoutes } from "./investigation-routes.js";
import contract from "./contract.json" with { type: "json" };

const supportedServices = contract.supported_services || ["ec2", "rds", "ecs", "lambda", "cloudwatch"];

const root = existsSync(new URL("./static/", import.meta.url))
  ? new URL("./static/", import.meta.url) : new URL("../webapp/static/", import.meta.url);
const files = {
  "/": ["index.html", "text/html; charset=utf-8"],
  "/static/style.css": ["style.css", "text/css; charset=utf-8"],
  "/static/report.css": ["report.css", "text/css; charset=utf-8"],
  "/static/app.js": ["app.js", "text/javascript; charset=utf-8"],
  "/static/fonts/NanumSquareB.otf": ["fonts/NanumSquareB.otf", "font/otf"],
  "/static/fonts/OFL.txt": ["fonts/OFL.txt", "text/plain; charset=utf-8"],
};
const responseHeaders = {
  "cache-control": "no-store", "x-content-type-options": "nosniff", "referrer-policy": "no-referrer",
  "content-security-policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
};
const json = (res, status, body) => {
  res.writeHead(status, { ...responseHeaders, "content-type": "application/json" });
  res.end(JSON.stringify(body));
};
const equal = (a, b) => {
  const left = Buffer.from(a), right = Buffer.from(b);
  return left.length === right.length && timingSafeEqual(left, right);
};

async function readQuery(req) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > 16_384) throw Object.assign(new Error("RequestTooLarge"), { httpStatus: 413 });
    chunks.push(chunk);
  }
  let body;
  try { body = JSON.parse(Buffer.concat(chunks)); } catch { throw Object.assign(new Error("InvalidJson"), { httpStatus: 400 }); }
  if (!body || Array.isArray(body) || Object.keys(body).some((key) => !["prompt", "language"].includes(key)) ||
      typeof body.prompt !== "string" || !body.prompt.trim() || body.prompt.length > 4000) {
    throw Object.assign(new Error("InvalidInput"), { httpStatus: 422 });
  }
  const language = body.language === undefined ? "ko" : body.language;
  if (!["ko", "en"].includes(language)) throw Object.assign(new Error("InvalidLanguage"), { httpStatus: 422 });
  return { prompt: body.prompt.trim(), language };
}

export function createApp(settings, dependencies = {}) {
  const live = settings.mode === "live";
  const runner = dependencies.runner || (live
    ? settings.agentBackend === "converse" ? new ConverseRunner(settings) : new LiveRunner(settings)
    : new SampleRunner());
  const store = dependencies.store || (live ? new S3Store(settings) : new MemoryStore(settings));
  const investigationService = dependencies.investigationService ||
    new InvestigationService(settings, { reportStore: store, ...dependencies.investigations });
  const sts = live && !dependencies.identity ? new STSClient({ region: settings.appRegion, maxAttempts: 3,
    requestHandler: { requestTimeout: 10000, connectionTimeout: 3000 } }) : null;
  const identity = dependencies.identity || (async () => (await sts.send(new GetCallerIdentityCommand({}))).Account);
  let activeQueries = 0;

  async function verifyAccount() {
    if (!live) return settings.accountId;
    let actual;
    try { actual = await identity(); }
    catch { throw Object.assign(new Error("AccountVerificationFailed"), { httpStatus: 503 }); }
    if (actual !== settings.accountId) throw Object.assign(new Error("AccountMismatch"), { httpStatus: 409 });
    return actual;
  }
  const investigationRoutes = createInvestigationRoutes({
    service: investigationService, verifyAccount, json, responseHeaders,
  });

  return http.createServer(async (req, res) => {
    const requestUrl = new URL(req.url, "http://localhost");
    const path = requestUrl.pathname;
    try {
      if (path.startsWith("/api/") && settings.accessToken) {
        const authorization = req.headers.authorization || "";
        if (!authorization.startsWith("Bearer ") || !equal(authorization.slice(7), settings.accessToken)) {
          return json(res, 401, { error: "AuthenticationRequired" });
        }
      }
      if (req.method === "GET" && path in files) {
        const [file, type] = files[path];
        res.writeHead(200, { ...responseHeaders, "content-type": type });
        return res.end(await readFile(fileURLToPath(new URL(file, root))));
      }
      if (req.method === "GET" && path === "/health") return json(res, 200, { status: "ok" });
      if (req.method === "GET" && path === "/api/context") {
        return json(res, 200, {
          account_id: await verifyAccount(), app_region: settings.appRegion, target_region: settings.targetRegion,
          mode: settings.mode, account_source: live ? "web_function_sts" : "synthetic_fixture", runtime_account_verified: false,
          observed_at: new Date().toISOString(), supported_services: supportedServices,
          lambda_scope: "event_functions_only", max_resources: settings.maxResources, max_metric_hours: settings.maxMetricHours,
          model: live ? settings.model : null, agent_backend: settings.agentBackend,
          model_processing_scope: settings.agentBackend === "converse" ? "global" : "app_region",
        });
      }
      if (await investigationRoutes(req, res, requestUrl)) return;
      if (req.method === "POST" && path === "/api/chat") {
        const { prompt, language } = await readQuery(req);
        await verifyAccount();
        if (activeQueries >= 2) return json(res, 429, { error: "ConcurrentQueryLimit" });
        activeQueries++;
        const controller = new AbortController();
        res.on("close", () => { if (!res.writableEnded) controller.abort(); });
        const record = {
          id: randomUUID(), prompt, language, mode: settings.mode, created_at: new Date().toISOString(),
          account_id: settings.accountId, app_region: settings.appRegion, target_region: settings.targetRegion,
          supported_services: supportedServices,
        };
        res.writeHead(200, { ...responseHeaders, "content-type": "text/event-stream; charset=utf-8", "x-accel-buffering": "no" });
        const emit = (event) => { if (!res.destroyed) res.write(`data: ${JSON.stringify(event)}\n\n`); };
        emit({ type: "started", ...record });
        const keepalive = setInterval(() => emit({ type: "heartbeat" }), 15000);
        try {
          for await (const event of runner.stream(prompt, { signal: controller.signal, language })) {
            if (controller.signal.aborted) break;
            if (event.type === "result") {
              const { type, ...result } = event;
              Object.assign(record, result, { report_available: true });
              try { await store.put(record); }
              catch (error) {
                record.report_available = error.recordSaved === true;
                record.errors.push(error.recordSaved ? "HistoryIndexWriteFailed" : "ReportPersistenceFailed");
                record.status = "partial";
              }
              const { bma_session_id, ...visible } = record;
              emit({ type: "complete", ...visible });
            } else emit(event);
          }
        } catch (error) {
          emit({ type: "error", code: error.code || "AppExecutionError", id: record.id });
        } finally { activeQueries--; clearInterval(keepalive); res.end(); }
        return;
      }
      if (req.method === "GET" && path === "/api/runs") {
        await verifyAccount();
        if ([...requestUrl.searchParams.keys()].some((key) => !["limit", "cursor"].includes(key))) {
          return json(res, 400, { error: "InvalidHistoryRequest" });
        }
        const rawLimit = requestUrl.searchParams.get("limit") || "10";
        if (!/^\d+$/.test(rawLimit)) return json(res, 400, { error: "InvalidHistoryLimit" });
        try {
          return json(res, 200, await store.list({
            limit: Number(rawLimit), cursor: requestUrl.searchParams.get("cursor") || undefined,
          }));
        } catch (error) {
          const invalid = ["InvalidHistoryLimit", "InvalidHistoryCursor"].includes(error.message);
          return json(res, invalid ? 400 : 503, { error: invalid ? error.message : "HistoryReadFailed" });
        }
      }
      const savedRun = /^\/api\/runs\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/.exec(path);
      if (req.method === "GET" && savedRun) {
        await verifyAccount();
        let record;
        try {
          record = await store.get(savedRun[1]);
          if (record) validateHistoryRecord(record, settings);
        } catch { return json(res, 503, { error: "ReportReadFailed" }); }
        if (!record) return json(res, 404, { error: "ReportNotFound" });
        const { bma_session_id, ...visible } = record;
        return json(res, 200, { ...visible, report_available: record.report_available !== false });
      }
      const match = /^\/api\/runs\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\/report\.(md|html|docx|pptx)$/.exec(path);
      if (req.method === "GET" && match) {
        let record;
        try { record = await store.get(match[1]); } catch { return json(res, 503, { error: "ReportReadFailed" }); }
        if (!record) return json(res, 404, { error: "ReportNotFound" });
        const format = match[2];
        const view = requestUrl.searchParams.get("view") || "";
        const theme = requestUrl.searchParams.get("theme") || "light";
        if (!["", "preview", "download"].includes(view) || !["light", "dark"].includes(theme) ||
            (format !== "html" && view)) return json(res, 400, { error: "InvalidReportView" });
        if (Object.hasOwn(OFFICE_MIME, format)) {
          let body;
          try { body = await renderOfficeReport(record, format, { accountIds: [settings.accountId] }); }
          catch (error) {
            return json(res, error.message === "OfficeReportTooLarge" ? 413 : 500, {
              error: error.message === "OfficeReportTooLarge" ? "OfficeReportTooLarge" : "OfficeExportFailed",
            });
          }
          res.writeHead(200, { ...responseHeaders, "content-type": OFFICE_MIME[format],
            "content-length": body.length, "content-disposition": `attachment; filename="aws-report-${match[1]}.${format}"` });
          return res.end(body);
        }
        res.writeHead(200, { ...responseHeaders, "content-type": format === "html" ? "text/html; charset=utf-8" : "text/markdown; charset=utf-8",
          "content-disposition": `${view === "preview" ? "inline" : "attachment"}; filename="aws-report-${match[1]}.${format}"` });
        return res.end(format === "html" ? renderHtml(record, {
          preview: view === "preview", redact: true, theme, accountIds: [settings.accountId],
        }) : renderMarkdown({ ...redactReportValue(record, reportAccountIds(record, [settings.accountId]), {
          strict: true, partial: Boolean(record.errors?.length),
        }), id: record.id }));
      }
      return json(res, 404, { error: "NotFound" });
    } catch (error) {
      if (!res.headersSent) return json(res, error.httpStatus || 500, { error: error.httpStatus ? error.message : "AppExecutionError" });
      res.end();
    }
  });
}
