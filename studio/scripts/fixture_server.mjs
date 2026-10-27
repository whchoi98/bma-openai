// Serve the real Studio routes and UI with in-memory jobs built from locally rendered files.
// Used by capture_screenshots.py: no AWS, BMA or model calls. A "complete" line on stdin finishes running jobs.
import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { createInterface } from "node:readline";
import { setTimeout as wait } from "node:timers/promises";
import { createStudioApp } from "../web/server.js";
import { TERMINAL, error, publicJob, validId } from "../web/config.js";

const [manifestPath, port] = process.argv.slice(2);
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
const jobs = new Map(manifest.history.map((job) => [job.id, job]));
const uploads = new Map();
const settings = { accessToken: manifest.access_key, accountId: "000000000000", model: manifest.model, appRegion: "us-east-1" };

function update(id, changes) {
  jobs.set(id, { ...jobs.get(id), ...changes, updated_at: new Date().toISOString() });
}

async function progress(id) {
  // Real phase names in worker order; the job then waits on "writing" until stdin completes it
  const completed = ["queued"];
  for (const phase of ["reading", "analyzing", "charting", "writing"]) {
    update(id, { phase, completed_steps: [...completed] });
    completed.push(phase);
    await wait(400);
  }
}

function complete() {
  for (const [id, job] of jobs) {
    if (TERMINAL.has(job.status)) continue;
    const { title, answer, artifacts, warnings } = manifest.draft;
    update(id, { status: "complete", phase: "done", title, answer, artifacts, warnings,
      completed_steps: ["queued", "reading", "analyzing", "charting", "writing", "packaging", "done"] });
  }
}

const store = {
  async upload(name, bytes) {
    const upload = { id: randomUUID(), name, size: bytes.length, extension: name.split(".").pop().toLowerCase() };
    uploads.set(upload.id, upload);
    return upload;
  },
  async list() {
    const rows = [...jobs.values()].sort((a, b) => b.created_at.localeCompare(a.created_at));
    return { jobs: rows.map(publicJob), next_cursor: null, complete: true };
  },
};

const fixtureJobs = {
  async create(body) {
    const id = validId(body.request_id);
    if (!jobs.has(id)) {
      const now = new Date().toISOString();
      jobs.set(id, { id, title: manifest.draft.title, prompt: body.prompt, created_at: now, updated_at: now,
        status: "running", phase: "queued", completed_steps: [], style: body.style, language: body.language,
        outputs: body.outputs, upload: uploads.get(body.upload_id), answer: "", artifacts: [], warnings: [], errors: [] });
      progress(id);
    }
    return { job: publicJob(jobs.get(id)) };
  },
  async get(id) {
    const job = jobs.get(validId(id));
    if (!job) throw error("JobNotFound", 404);
    return { job: publicJob(job) };
  },
  async cancel(id) {
    return this.get(id);
  },
  async *events(id, signal) {
    let previous = "";
    while (!signal.aborted) {
      const result = await this.get(id);
      const current = JSON.stringify(result);
      if (current !== previous) { previous = current; yield { type: "snapshot", ...result }; }
      if (TERMINAL.has(result.job.status)) { yield { type: "complete", ...result }; return; }
      try { await wait(200, undefined, { signal }); } catch { return; }
    }
  },
  async artifact(id, artifactId) {
    const item = (jobs.get(validId(id))?.artifacts || []).find((row) => row.id === artifactId);
    if (!item) throw error("ArtifactNotFound", 404);
    return { ...item, bytes: readFileSync(item.path) };
  },
};

const server = createStudioApp(settings, { store, jobs: fixtureJobs, identity: async () => settings.accountId });
server.listen(Number(port), "127.0.0.1", () => console.log("ready"));
createInterface({ input: process.stdin }).on("line", (line) => { if (line.trim() === "complete") complete(); });
process.on("SIGTERM", () => server.close(() => process.exit(0)));
