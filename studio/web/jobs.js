import { LambdaClient, InvokeCommand } from "@aws-sdk/client-lambda";
import { setTimeout as wait } from "node:timers/promises";
import { LIMITS, STYLES, FORMATS, TERMINAL, error, validId, publicJob } from "./config.js";
import { sha256 } from "./store.js";

export class Jobs {
  constructor(settings, store, { dispatch, clock = Date.now } = {}) {
    this.settings = settings; this.store = store; this.clock = clock;
    this.dispatch = dispatch || this.invoke.bind(this);
    this.lambda = null;
  }
  async invoke(id) {
    this.lambda ||= new LambdaClient({ region: this.settings.appRegion, maxAttempts: 3,
      requestHandler: { connectionTimeout: 3000, requestTimeout: 10000 } });
    const result = await this.lambda.send(new InvokeCommand({
      FunctionName: this.settings.workerArn, InvocationType: "Event", Payload: Buffer.from(JSON.stringify({ job_id: id })),
    }));
    if (result.StatusCode !== 202) throw error("WorkerUnavailable", 503);
  }
  async create(body) {
    const allowed = ["request_id", "upload_id", "notes", "prompt", "outputs", "style", "language", "source_job_id"];
    if (!body || Array.isArray(body) || Object.keys(body).some((key) => !allowed.includes(key))) throw error("InvalidRequest");
    const id = validId(body.request_id);
    const prompt = body.prompt === undefined ? "" : body.prompt;
    if (typeof prompt !== "string" || prompt.length > LIMITS.promptCharacters) throw error("InvalidPrompt");
    if (!STYLES.some((style) => style.id === body.style)) throw error("InvalidStyle");
    if (!["ko", "en"].includes(body.language)) throw error("InvalidLanguage");
    if (!Array.isArray(body.outputs) || !body.outputs.length || body.outputs.length > 4 ||
        new Set(body.outputs).size !== body.outputs.length || body.outputs.some((f) => !FORMATS.includes(f))) throw error("InvalidOutputs");
    if (body.notes !== undefined && (typeof body.notes !== "string" || body.notes.length > LIMITS.notesCharacters)) throw error("NotesTooLong");
    let previous, upload;
    if (body.source_job_id) {
      previous = await this.store.input(validId(body.source_job_id));
      if (!previous) throw error("SourceNotFound", 404);
    }
    if (body.upload_id) {
      upload = (await this.store.uploadMeta(validId(body.upload_id)))?.value;
      if (!upload) throw error("SourceNotFound", 404);
    } else upload = previous?.value.upload || null;
    if (upload) upload = { id: upload.id, name: upload.name, size: upload.size, sha256: upload.sha256 };
    const notes = body.notes ?? previous?.value.notes ?? "";
    if (!upload && !notes.trim()) throw error("SourceRequired");
    const input = {
      ...this.store.scope(), id, created_at: new Date(this.clock()).toISOString(),
      upload, notes, prompt: prompt.trim() || (body.language === "ko" ? "제공한 자료를 업무용으로 정리해 주세요." : "Prepare business materials from the supplied source."),
      outputs: body.outputs, style: body.style, language: body.language,
      ...(body.source_job_id ? { source_job_id: body.source_job_id } : {}),
      input_hash: sha256(JSON.stringify({ ...body, outputs: [...body.outputs].sort() })),
    };
    await this.store.create(input);
    await this.kick(id);
    return this.get(id, false);
  }
  async kick(id) {
    const saved = await this.store.update(id, (value) => {
      if (TERMINAL.has(value.status) || Date.parse(value.lease_until || "") > this.clock() ||
          this.clock() - Date.parse(value.last_dispatch_at || "1970-01-01T00:00:00Z") < 10000) return null;
      return { ...value, last_dispatch_at: new Date(this.clock()).toISOString() };
    });
    if (saved) {
      try { await this.dispatch(id); } catch { throw error("WorkerUnavailable", 503); }
    }
  }
  async get(id, reconcile = true) {
    validId(id);
    let state = await this.store.state(id);
    if (!state) {
      const input = await this.store.input(id);
      if (!input) throw error("JobNotFound", 404);
      state = await this.store.create(input.value);
    }
    if (reconcile && !TERMINAL.has(state.value.status)) {
      await this.kick(id); state = await this.store.state(id);
    }
    return { job: publicJob(state.value) };
  }
  async cancel(id) {
    await this.get(id, false);
    await this.store.update(id, (value) => TERMINAL.has(value.status) ? null : { ...value, cancel_requested: true });
    await this.kick(id);
    return this.get(id, false);
  }
  async *events(id, signal) {
    let previous = "", ticks = 0;
    const deadline = this.clock() + 360000;
    while (!signal.aborted && this.clock() < deadline) {
      const result = await this.get(id);
      const current = JSON.stringify(result);
      if (current !== previous) { previous = current; yield { type: "snapshot", ...result }; }
      else if (++ticks % 10 === 0) yield { type: "heartbeat" };
      if (TERMINAL.has(result.job.status)) { yield { type: "complete", ...result }; return; }
      try { await wait(1000, undefined, { signal }); } catch (cause) { if (!signal.aborted) throw cause; }
    }
  }
  async artifact(id, artifactId) {
    const saved = await this.store.state(validId(id));
    if (!saved) throw error("JobNotFound", 404);
    const item = (saved.value.artifacts || []).find((row) => row.id === artifactId);
    if (!item || !/^[A-Za-z0-9_-]{1,100}$/.test(artifactId) ||
        !item.key.startsWith(`jobs/${id}/outputs/`)) throw error("ArtifactNotFound", 404);
    const object = await this.store.get(item.key, LIMITS.outputBytes);
    if (!object || sha256(object.bytes) !== item.sha256) throw error("ArtifactUnavailable", 503);
    return { ...item, bytes: object.bytes };
  }
}
