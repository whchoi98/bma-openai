import http from "node:http";
import { timingSafeEqual } from "node:crypto";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { STSClient, GetCallerIdentityCommand } from "@aws-sdk/client-sts";
import { StudioStore, readBody } from "./store.js";
import { Jobs } from "./jobs.js";
import { LIMITS, STYLES, FORMATS, error } from "./config.js";

const root = new URL("./static/", import.meta.url);
const staticFiles = {
  "/": ["index.html", "text/html; charset=utf-8"],
  "/static/app.js": ["app.js", "text/javascript; charset=utf-8"],
  "/static/style.css": ["style.css", "text/css; charset=utf-8"],
  "/static/fonts/NanumSquareB.otf": ["fonts/NanumSquareB.otf", "font/otf"],
  "/static/fonts/OFL.txt": ["fonts/OFL.txt", "text/plain"],
};
const headers = {
  "cache-control": "no-store", "x-content-type-options": "nosniff", "referrer-policy": "no-referrer",
  "content-security-policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; font-src 'self' data:; connect-src 'self'; frame-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
};
const json = (res, status, body) => {
  res.writeHead(status, { ...headers, "content-type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(body));
};
async function body(req, maximum) {
  return readBody(req.iterator({ destroyOnReturn: false }), maximum);
}
async function jsonBody(req) {
  const bytes = await body(req, 256 * 1024);
  try { return JSON.parse(bytes); } catch { throw error("InvalidJson", 400); }
}
export function createStudioApp(settings, dependencies = {}) {
  const store = dependencies.store || new StudioStore(settings);
  const jobs = dependencies.jobs || new Jobs(settings, store, dependencies);
  const sts = dependencies.identity ? null : new STSClient({ region: settings.appRegion, maxAttempts: 3 });
  const identity = dependencies.identity || (async () => (await sts.send(new GetCallerIdentityCommand({}))).Account);
  return http.createServer(async (req, res) => {
    const url = new URL(req.url, "http://localhost"), path = url.pathname;
    try {
      if (["GET", "HEAD"].includes(req.method) && staticFiles[path]) {
        const [file, mime] = staticFiles[path];
        const bytes = await readFile(fileURLToPath(new URL(file, root)));
        const cacheControl = req.headers.authorization || req.headers.cookie ? "no-store"
          : path === "/" ? "public, max-age=0, s-maxage=60, must-revalidate"
          : "public, max-age=300, s-maxage=3600, must-revalidate";
        res.writeHead(200, { ...headers, "content-type": mime,
          "cache-control": cacheControl, "vary": "Authorization, Cookie", "content-length": bytes.length });
        return res.end(req.method === "HEAD" ? undefined : bytes);
      }
      if (path === "/health") return json(res, 200, { status: "ok" });
      if (!path.startsWith("/api/")) return json(res, 404, { error: "NotFound" });
      const expected = Buffer.from("Bearer " + settings.accessToken);
      const actual = Buffer.from(req.headers.authorization || "");
      if (expected.length !== actual.length || !timingSafeEqual(expected, actual)) return json(res, 401, { error: "AuthenticationRequired" });
      if (await identity() !== settings.accountId) return json(res, 409, { error: "AccountMismatch" });
      if (req.method === "GET" && path === "/api/config") {
        return json(res, 200, { model: settings.model, app_region: settings.appRegion,
          styles: STYLES, limits: LIMITS, formats: FORMATS });
      }
      if (req.method === "POST" && path === "/api/uploads") {
        let name;
        try { name = decodeURIComponent(req.headers["x-file-name"] || ""); } catch { throw error("InvalidFileName"); }
        if (!name || name.length > 120 || /[/\\\u0000-\u001f]/.test(name) || !/\.(xlsx|csv|txt|md)$/i.test(name)) throw error("UnsupportedFile");
        const bytes = await body(req, LIMITS.fileBytes);
        const upload = await store.upload(name, bytes);
        return json(res, 201, { upload: { id: upload.id, name: upload.name, size: upload.size, extension: upload.extension } });
      }
      if (path === "/api/jobs" && req.method === "POST") return json(res, 202, await jobs.create(await jsonBody(req)));
      if (path === "/api/jobs" && req.method === "GET") {
        if ([...url.searchParams.keys()].some((key) => !["limit", "cursor"].includes(key))) throw error("InvalidRequest");
        return json(res, 200, await store.list({ limit: Number(url.searchParams.get("limit") || 10),
          cursor: url.searchParams.get("cursor") || undefined }));
      }
      const match = /^\/api\/jobs\/([a-f0-9-]{36})(?:\/(events|cancel|artifacts)(?:\/([A-Za-z0-9_-]{1,100}))?)?$/.exec(path);
      if (!match) return json(res, 404, { error: "NotFound" });
      const [, id, action, asset] = match;
      if (!action && req.method === "GET") return json(res, 200, await jobs.get(id));
      if (action === "cancel" && req.method === "POST") {
        const input = await jsonBody(req);
        if (!input || Array.isArray(input) || Object.keys(input).length) throw error("InvalidRequest");
        return json(res, 202, await jobs.cancel(id));
      }
      if (action === "artifacts" && asset && req.method === "GET") {
        if ([...url.searchParams.keys()].some((key) => key !== "view") ||
            !["", "inline"].includes(url.searchParams.get("view") || "")) throw error("InvalidRequest");
        const artifact = await jobs.artifact(id, asset);
        const inline = url.searchParams.get("view") === "inline" && ["image/png", "image/svg+xml", "text/html"].includes(artifact.mime);
        res.writeHead(200, { ...headers,
          "content-security-policy": "default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:; sandbox",
          "content-type": artifact.mime, "content-length": artifact.bytes.length,
          "content-disposition": `${inline ? "inline" : "attachment"}; filename*=UTF-8''${encodeURIComponent(artifact.filename)}` });
        return res.end(artifact.bytes);
      }
      if (action === "events" && req.method === "GET") {
        const controller = new AbortController();
        res.on("close", () => controller.abort());
        await jobs.get(id);
        res.writeHead(200, { ...headers, "content-type": "text/event-stream", "x-accel-buffering": "no" });
        try { for await (const event of jobs.events(id, controller.signal)) {
          if (!res.destroyed) res.write(`data: ${JSON.stringify(event)}\n\n`);
        } } finally { if (!res.destroyed) res.end(); }
        return;
      }
      return json(res, 405, { error: "MethodNotAllowed" });
    } catch (cause) {
      req.resume();
      const code = cause.httpStatus ? cause.code || cause.message : "ServiceUnavailable";
      if (!res.headersSent) json(res, cause.httpStatus || 503, { error: code });
      else if (!res.destroyed) res.end(`data: ${JSON.stringify({ type: "error", code })}\n\n`);
    }
  });
}
