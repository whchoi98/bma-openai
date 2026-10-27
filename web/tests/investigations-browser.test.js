import assert from "node:assert/strict";
import test from "node:test";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "esbuild";

// Run with BMA_UI_PLAYWRIGHT pointing to an installed Playwright module.
// The server and all API responses are local; no AWS or model calls are made.
test("investigation browser flow preserves single questions, reconnects, history, cancellation and display preferences", {
  skip: !process.env.BMA_UI_PLAYWRIGHT,
}, async () => {
  const { chromium } = await import(pathToFileURL(process.env.BMA_UI_PLAYWRIGHT).href);
  const root = fileURLToPath(new URL("../../", import.meta.url));
  const bundle = await build({
    entryPoints: [root + "web/ui/app.js"], bundle: true, write: false, platform: "browser",
    format: "iife", define: { "process.env.NODE_ENV": '"production"' },
  });
  const evidence = {
    tool: "list_ec2_instances", service: "ec2", status: "ok", region: "ap-northeast-2", mode: "sample",
    account_id: "123456789012", observed_at: "2026-10-27T00:00:00Z", duration_ms: 3,
    count: 1, resource_count: 1, data: [{ instance_id: "i-example", state: "running" }],
    api_calls: [{ service: "ec2", api: "DescribeInstances", region: "ap-northeast-2", success: true }],
  };
  const procedures = ["inventory", "service-health", "security-review", "operations-report"].map((id) => ({
    id, version: "1.0.0", sha256: "a".repeat(64), name: { ko: `${id} 절차`, en: `${id} procedure` },
    description: { ko: "실제 조회 결과를 확인합니다.", en: "Review observed query results." },
    steps: ["account", "discovery", "checks", "report"].map((step) => ({
      id: step, label: { ko: `${step} 확인`, en: `${step} check` }, tools: [],
    })),
  }));
  const sessions = new Map(), runs = new Map(), requests = [];
  let firstInvestigationId, reconnectEvents = 0, cancelNext = false;
  function record(run) {
    return {
      id: run.id, prompt: run.prompt, language: run.language, answer: run.answer,
      status: run.status, evidence: run.evidence, errors: [], report_available: run.status === "complete",
      account_id: "123456789012", target_region: "ap-northeast-2", app_region: "us-east-1",
      created_at: run.created_at, mode: "sample",
    };
  }
  function finish(investigation, run, status = "complete") {
    run.status = status;
    run.phase = status;
    run.answer = status === "cancelled" ? "Cancelled answer" : `Completed: ${run.prompt}`;
    run.evidence = [evidence];
    run.procedure_steps = investigation.procedure.steps.map((step) => ({ ...step, status: "complete" }));
    run.result = record(run);
    investigation.status = status;
    investigation.active_run_id = null;
    investigation.turns.find((turn) => turn.id === run.id).status = status;
  }
  const server = createServer(async (req, res) => {
    const url = new URL(req.url, "http://localhost"), pathname = url.pathname;
    requests.push({ method: req.method, path: pathname, authorization: req.headers.authorization });
    function json(value, status = 200) {
      res.writeHead(status, { "Content-Type": "application/json" });
      res.end(JSON.stringify(value));
    }
    if (pathname === "/") {
      res.setHeader("Content-Type", "text/html");
      return res.end(await readFile(root + "webapp/static/index.html"));
    }
    if (pathname === "/static/app.js") {
      res.setHeader("Content-Type", "application/javascript");
      return res.end(bundle.outputFiles[0].text);
    }
    if (pathname === "/static/style.css") {
      res.setHeader("Content-Type", "text/css");
      return res.end(await readFile(root + "webapp/static/style.css"));
    }
    if (pathname === "/static/fonts/NanumSquareB.otf") {
      res.setHeader("Content-Type", "font/otf");
      return res.end(await readFile(root + "webapp/static/fonts/NanumSquareB.otf"));
    }
    if (!pathname.startsWith("/api/")) return json({}, 404);
    if (req.headers.authorization !== "Bearer browser-secret") return json({ error: "AuthenticationRequired" }, 401);
    if (pathname === "/api/context") return json({
      mode: "sample", account_id: "123456789012", app_region: "us-east-1", target_region: "ap-northeast-2",
      model: "openai.gpt-6-luna",
    });
    if (pathname === "/api/procedures") return json({ enabled: true, procedures });
    if (pathname === "/api/runs") return json({ runs: [], next_cursor: null, complete: true });
    if (pathname === "/api/investigations" && req.method === "GET") {
      return json({ investigations: [...sessions.values()], next_cursor: null, complete: true });
    }
    let input = "";
    for await (const chunk of req) input += chunk;
    const body = input ? JSON.parse(input) : {};
    if (pathname === "/api/chat") {
      res.setHeader("Content-Type", "text/event-stream");
      return res.end(`data: ${JSON.stringify({ type: "complete", ...record({
        id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", prompt: body.prompt,
        status: "complete", answer: "Single question answer", evidence: [evidence],
      }) })}\n\n`);
    }
    if (req.method === "POST" && (pathname === "/api/investigations" || pathname.endsWith("/turns"))) {
      let investigation;
      if (pathname.endsWith("/turns")) investigation = sessions.get(pathname.split("/")[3]);
      else {
        investigation = {
          id: body.request_id, title: body.prompt, status: "queued",
          created_at: "2026-10-27T00:00:00Z", updated_at: "2026-10-27T00:00:00Z",
          expires_at: "2099-10-27T06:00:00Z", procedure: procedures.find((p) => p.id === body.procedure_id), turns: [],
        };
        sessions.set(investigation.id, investigation);
        firstInvestigationId ||= investigation.id;
      }
      const run = {
        id: body.request_id, investigation_id: investigation.id, prompt: body.prompt, language: body.language,
        created_at: "2026-10-27T00:00:00Z", updated_at: "2026-10-27T00:00:00Z",
        status: "running", phase: "running", answer: "", evidence: [], errors: [], result: null,
        procedure_steps: investigation.procedure.steps.map((step) => ({ ...step, status: "pending" })),
      };
      investigation.active_run_id = run.id;
      investigation.status = "running";
      investigation.turns.push({ id: run.id, prompt: run.prompt, language: run.language, status: run.status, created_at: run.created_at });
      runs.set(run.id, run);
      return json({ investigation, run }, 202);
    }
    const parts = pathname.split("/"), investigation = sessions.get(parts[3]);
    if (!investigation) return json({ error: "InvestigationNotFound" }, 404);
    const run = runs.get(parts[5] || investigation.turns.at(-1).id);
    if (pathname.endsWith("/events")) {
      res.setHeader("Content-Type", "text/event-stream");
      if ((investigation.id === firstInvestigationId && reconnectEvents++ === 0) || cancelNext) {
        run.answer = "Partial answer";
        run.evidence = [evidence];
        const event = `data: ${JSON.stringify({ type: "snapshot", investigation, run })}\n\n`;
        return res.end(event + event);
      }
      finish(investigation, run);
      return res.end(`data: ${JSON.stringify({ type: "snapshot", investigation, run })}\n\n` +
        `data: ${JSON.stringify({ type: "complete", ...run.result })}\n\n`);
    }
    if (pathname.endsWith("/cancel")) {
      assert.deepEqual(body, {});
      finish(investigation, run, "cancelled");
      return json({ accepted: true }, 202);
    }
    return json({ investigation, run });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  let browser;
  try {
    browser = await chromium.launch({ headless: true, args: ["--no-sandbox"] });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(`http://127.0.0.1:${server.address().port}`);
    await page.locator("#access-key").fill("browser-secret");
    await page.locator("#connect").click();
    await page.waitForFunction(() => !document.getElementById("submit").disabled);
    assert.equal(await page.locator("#single-question-workspace").isVisible(), true);
    assert.equal(await page.locator("#investigation-workspace").isVisible(), false);
    await page.locator("#prompt").fill("Single query");
    await page.locator("#submit").click();
    await page.waitForFunction(() => document.getElementById("answer").textContent.includes("Single question answer"));
    await page.locator("#mode-investigation").click();
    await page.waitForFunction(() => document.getElementById("procedure-picker").options.length === 4);
    await page.locator("#investigation-prompt").fill("Inspect EC2 in 123456789012");
    await page.locator("#investigation-submit").click();
    await page.waitForFunction(() => document.getElementById("investigation-connection").textContent.includes("끊겼습니다"));
    assert.equal(await page.locator("#trace-body tr").count(), 1);
    assert.equal(await page.locator("#download-md").isDisabled(), true);
    assert.equal(await page.locator("#investigation-submit").isDisabled(), true);
    assert.equal(await page.locator("#procedure-picker").isDisabled(), true);
    await page.locator("#investigation-reconnect").click();
    await page.waitForFunction(() => !document.getElementById("download-md").disabled);
    assert.match(await page.locator("#answer").innerText(), /Completed:/);
    assert.doesNotMatch(await page.locator("body").innerText(), /123456789012/);
    await page.locator("#investigation-prompt").fill("Summarize previous evidence");
    await page.locator("#investigation-submit").click();
    await page.waitForFunction(() => document.querySelectorAll("#investigation-turns button").length === 2 &&
      document.getElementById("answer").textContent.includes("Summarize previous evidence"));
    await page.locator("#investigation-turns button").first().click();
    await page.waitForFunction(() => document.getElementById("answer").textContent.includes("Inspect EC2"));
    await page.locator("#mode-question").click();
    assert.match(await page.locator("#answer").innerText(), /Single question answer/);
    const postsBeforeReload = requests.filter((r) => r.method === "POST").length;
    await page.reload();
    assert.equal(await page.locator("#access-key").inputValue(), "");
    assert.equal(await page.locator("#single-question-workspace").isVisible(), true);
    await page.locator("#access-key").fill("browser-secret");
    await page.locator("#connect").click();
    await page.locator("#mode-investigation").click();
    await page.waitForFunction(() => document.getElementById("answer").textContent.includes("Summarize previous evidence"));
    assert.equal(requests.filter((r) => r.method === "POST").length, postsBeforeReload);
    await page.locator("#language-toggle").click();
    assert.equal(await page.locator("#investigation-submit").innerText(), "Send follow-up");
    await page.locator("#theme-toggle").click();
    assert.equal(await page.locator("html").getAttribute("data-theme"), "dark");
    assert.match(await page.locator("#procedure-picker").evaluate((node) => getComputedStyle(node).fontFamily), /NanumSquare OTF Bold/);
    assert.equal(await page.locator("#procedure-steps li").count(), 4);
    if (process.env.BMA_UI_SCREENSHOT) {
      await page.screenshot({ path: process.env.BMA_UI_SCREENSHOT, fullPage: true, animations: "disabled" });
    }
    cancelNext = true;
    await page.locator("#investigation-new").click();
    await page.locator("#investigation-prompt").fill("Cancel this local sample");
    await page.locator("#investigation-submit").click();
    await page.waitForFunction(() => document.getElementById("investigation-connection").textContent.includes("connection closed"));
    await page.locator("#investigation-cancel").click();
    await page.locator("#investigation-reconnect").click();
    await page.waitForFunction(() => document.getElementById("run-status").textContent === "Cancelled");
    const stored = await page.evaluate(() => Object.fromEntries(Object.entries(localStorage)));
    assert.deepEqual(Object.keys(stored).sort(), ["aws-desk-language", "aws-desk-last-investigation", "aws-desk-theme"]);
    assert.doesNotMatch(JSON.stringify(stored), /browser-secret|123456789012|Inspect EC2|Partial answer|Completed:/);
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    assert.doesNotMatch(await page.locator("body").innerText(), /[—·]/);
    assert.deepEqual(errors, []);
    for (const request of requests.filter((request) => request.path.endsWith("/events"))) {
      assert.equal(request.method, "GET");
      assert.equal(request.authorization, "Bearer browser-secret");
    }
  } finally {
    await browser?.close();
    await new Promise((resolve) => server.close(resolve));
  }
});
