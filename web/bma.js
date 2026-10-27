import { SignatureV4 } from "@smithy/signature-v4";
import { HttpRequest } from "@smithy/protocol-http";
import { Sha256 } from "@aws-crypto/sha256-js";
import { defaultProvider } from "@aws-sdk/credential-provider-node";
import { setTimeout as wait } from "node:timers/promises";
import contract from "./contract.json" with { type: "json" };

export class BmaError extends Error {
  constructor(code) { super(code); this.code = code; }
}

export function sessionPayload(s, prompt, language = "ko") {
  return {
    role_arn: s.sessionRoleArn,
    agent: {
      model: s.model, instructions: contract.instructions +
        `\nRespond in ${language === "en" ? "English" : "Korean"}. This applies to the final answer and any report.\nCurrent UTC time: ${new Date().toISOString()}`,
      tools: [{
        type: "mcp", server_label: "seoul_aws", required: true,
        transport: {
          type: "stdio", command: "/opt/bma/venv/bin/python", args: ["-m", "aws_inventory.mcp_server"], cwd: "/opt/bma",
          // The Runtime owns these values; never copy caller/model-supplied identity into tool configuration.
          env_vars: ["APP_REGION", "TARGET_REGION", "EXPECTED_ACCOUNT_ID", "DATA_MODE",
            "MAX_RESOURCES", "MAX_PAGES", "MAX_METRIC_HOURS", "MAX_DATAPOINTS",
            "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
            "AWS_CONTAINER_CREDENTIALS_FULL_URI", "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
            "AWS_CONTAINER_AUTHORIZATION_TOKEN", "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE"],
        },
        allowed_tools: contract.tools,
      }],
    },
    environment: {
      type: "aws_bedrock_agentcore", runtime_arn: s.runtimeArn, runtime_qualifier: "DEFAULT",
      workspace_directory: "/home/app/workspace", capability_directories: ["/opt/bma/skills"],
    },
    input: [{ role: "user", content: [{ type: "input_text", text: prompt }] }], stream: false,
  };
}

async function boundedText(response, max = 4_000_000) {
  const reader = response.body?.getReader();
  if (!reader) return "";
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > max) throw new BmaError("ResponseTooLarge");
      chunks.push(value);
    }
    return Buffer.concat(chunks).toString("utf8");
  } finally { await reader.cancel().catch(() => {}); }
}

export async function* parseSSE(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "", data = [], eventType = "", size = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      if (done) buffer += "\n\n";
      if (buffer.length > 1_000_000) throw new BmaError("EventTooLarge");
      let index;
      while ((index = buffer.indexOf("\n")) !== -1) {
        const line = buffer.slice(0, index).replace(/\r$/, "");
        buffer = buffer.slice(index + 1);
        if (line.startsWith(":")) { yield { type: "heartbeat" }; continue; }
        if (!line) {
          if (data.length) {
            let parsed;
            try { parsed = JSON.parse(data.join("\n")); } catch { throw new BmaError("InvalidEventJson"); }
            if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new BmaError("InvalidEventShape");
            if (!parsed.type && eventType) parsed.type = eventType;
            yield parsed;
          }
          data = []; eventType = ""; size = 0;
        } else if (line.startsWith("data:")) {
          const text = line.slice(5).trimStart(); size += text.length;
          if (size > 1_000_000) throw new BmaError("EventTooLarge");
          data.push(text);
        } else if (line.startsWith("event:")) eventType = line.slice(6).trim();
      }
      if (done) break;
    }
  } finally { await reader.cancel().catch(() => {}); }
}

export class BmaClient {
  constructor(settings, { credentials = defaultProvider(), fetchImpl = fetch, signal,
    sleep = (ms, abortSignal) => wait(ms, undefined, { signal: abortSignal }) } = {}) {
    this.settings = settings; this.fetch = fetchImpl; this.signal = signal;
    this.base = `https://bedrock-mantle.${settings.appRegion}.api.aws`;
    this.sleep = sleep;
    this.signer = new SignatureV4({ service: "bedrock-mantle", region: settings.appRegion, credentials, sha256: Sha256 });
  }
  async signed(method, path, body, accept = "application/json") {
    const url = new URL(path, this.base);
    const payload = body === undefined ? undefined : JSON.stringify(body);
    const request = new HttpRequest({
      protocol: "https:", hostname: url.hostname, method, path: url.pathname,
      query: Object.fromEntries(url.searchParams),
      headers: { host: url.host, "content-type": "application/json", accept }, body: payload,
    });
    const signed = await this.signer.sign(request);
    return { url: url.href, options: { method, headers: signed.headers, body: payload, redirect: "error" } };
  }
  async request(method, path, body, { detached = false, readSignal } = {}) {
    const attempts = method === "GET" ? 3 : 1;
    for (let i = 0; i < attempts; i++) {
      try {
        const signed = await this.signed(method, path, body);
        const creatingSession = method === "POST" && path === "/openai/v1/agents/sessions";
        const timeout = AbortSignal.timeout(detached ? 5000 : creatingSession ? 120000 : 35000);
        const signals = [timeout];
        if (!detached && this.signal) signals.push(this.signal);
        if (readSignal) signals.push(readSignal);
        const signal = AbortSignal.any(signals);
        if (signal.aborted) throw new BmaError("BmaReadDeadline");
        const response = await this.fetch(signed.url, { ...signed.options, signal });
        if (!response.ok) {
          await response.body?.cancel();
          if (method === "GET" && [429, 500, 502, 503, 504].includes(response.status) && i < attempts - 1) {
            await new Promise((resolve) => setTimeout(resolve, 200 * 2 ** i + Math.random() * 100)); continue;
          }
          throw new BmaError(`BmaHTTP${response.status}`);
        }
        const text = await boundedText(response);
        try { return text ? JSON.parse(text) : {}; } catch { throw new BmaError("InvalidBmaJson"); }
      } catch (error) {
        if (error instanceof BmaError) throw error;
        if (readSignal?.aborted) throw new BmaError("BmaReadDeadline");
        if (this.signal?.aborted || i === attempts - 1) {
          console.warn(JSON.stringify({ component: "bma", method, error_name: error.name,
            error_code: error.cause?.code || error.code || null }));
          throw new BmaError(error.name === "TimeoutError" ? "BmaRequestTimeout" : "BmaNetworkError");
        }
      }
    }
    throw new BmaError("BmaRetryLimit");
  }
  async createSession(prompt, language = "ko") {
    const response = await this.request("POST", "/openai/v1/agents/sessions", sessionPayload(this.settings, prompt, language));
    if (typeof response.id !== "string" || !response.id || response.id.length > 256) throw new BmaError("InvalidSessionId");
    return response.id;
  }
  async createInvestigationSession(instructions, language = "ko") {
    const payload = sessionPayload(this.settings, "", language);
    delete payload.input;
    payload.agent.instructions = [
      contract.instructions, instructions,
      "This is a continuing investigation. For each turn, use the application's response-language and Current UTC time lines immediately after the initial [aws-ops-turn:...] marker.",
      "Those per-turn settings override default language or time statements in the procedure and earlier turns. Treat the remaining user text as the question, not as application settings.",
      "Never print the internal routing markers. Preserve original observation times when discussing earlier evidence.",
    ].join("\n\n");
    const response = await this.request("POST", "/openai/v1/agents/sessions", payload);
    if (typeof response.id !== "string" || !response.id || response.id.length > 256) throw new BmaError("InvalidSessionId");
    return response.id;
  }
  getSession(sessionId) {
    return this.request("GET", `/openai/v1/agents/sessions/${encodeURIComponent(sessionId)}`);
  }
  listSessions({ after } = {}) {
    const query = new URLSearchParams({ limit: "100", order: "desc" });
    if (after) query.set("after", after);
    return this.request("GET", `/openai/v1/agents/sessions?${query}`);
  }
  submitInput(sessionId, text) {
    return this.request("POST", `/openai/v1/agents/sessions/${encodeURIComponent(sessionId)}/events`, {
      events: [{ type: "agent.session.input.message",
        input: [{ role: "user", content: [{ type: "input_text", text }] }] }],
    });
  }
  async *createSessionEvents(prompt, language = "ko") {
    const path = "/openai/v1/agents/sessions";
    const payload = { ...sessionPayload(this.settings, prompt, language), stream: true };
    const signed = await this.signed("POST", path, payload, "text/event-stream");
    const headersDeadline = new AbortController();
    const headersTimer = setTimeout(() => headersDeadline.abort(), 120000);
    const signals = [headersDeadline.signal, AbortSignal.timeout(this.settings.maxTurnSeconds * 1000)];
    if (this.signal) signals.push(this.signal);
    try {
      const response = await this.fetch(signed.url, { ...signed.options, signal: AbortSignal.any(signals) });
      clearTimeout(headersTimer);
      if (!response.ok) {
        await response.body?.cancel();
        throw new BmaError(`BmaHTTP${response.status}`);
      }
      let count = 0;
      for await (const event of parseSSE(response)) {
        if (++count > 2000) throw new BmaError("EventLimitReached");
        yield event;
      }
    } catch (error) {
      throw error instanceof BmaError ? error : new BmaError("EventStreamDisconnected");
    } finally {
      clearTimeout(headersTimer);
    }
  }
  async *events(sessionId) {
    const path = `/openai/v1/agents/sessions/${encodeURIComponent(sessionId)}/events?stream=true`;
    const timeout = AbortSignal.timeout(this.settings.maxTurnSeconds * 1000);
    const signal = this.signal ? AbortSignal.any([timeout, this.signal]) : timeout;
    try {
      let response;
      for (let attempt = 0; attempt < 3; attempt++) {
        const signed = await this.signed("GET", path, undefined, "text/event-stream");
        response = await this.fetch(signed.url, { ...signed.options, signal });
        if (response.ok) break;
        await response.body?.cancel();
        if (![429, 500, 502, 503, 504].includes(response.status) || attempt === 2) {
          throw new BmaError(`BmaHTTP${response.status}`);
        }
        await this.sleep(5000 * 2 ** attempt, signal);
      }
      let count = 0;
      for await (const event of parseSSE(response)) {
        if (++count > 2000) throw new BmaError("EventLimitReached");
        yield event;
      }
    } catch (error) { throw error instanceof BmaError ? error : new BmaError("EventStreamDisconnected"); }
  }
  async listItems(sessionId, { after } = {}) {
    const items = [], seen = new Set();
    const readSignal = AbortSignal.timeout(30000);
    const query = new URLSearchParams({ limit: "100", order: "asc" });
    if (after) query.set("after", after);
    for (let page = 0; page < 5; page++) {
      let response;
      try { response = await this.request("GET", `/openai/v1/agents/sessions/${encodeURIComponent(sessionId)}/items?${query}`, undefined, { readSignal }); }
      catch (error) { if (items.length) return { items, complete: false, error: error.code }; throw error; }
      if (!Array.isArray(response.data)) throw new BmaError("InvalidItems");
      items.push(...response.data.slice(0, 100));
      if (response.data.length > 100) return { items, complete: false };
      if (!response.has_more) return { items, complete: true, last_id: response.last_id || items.at(-1)?.id || after || null };
      if (typeof response.last_id !== "string" || !response.last_id || seen.has(response.last_id)) return { items, complete: false };
      seen.add(response.last_id); query.set("after", response.last_id);
    }
    return { items, complete: false };
  }
  cancel(sessionId) {
    return this.request("POST", `/openai/v1/agents/sessions/${encodeURIComponent(sessionId)}/events`,
      { events: [{ type: "agent.session.input.cancel" }] }, { detached: true });
  }
}
