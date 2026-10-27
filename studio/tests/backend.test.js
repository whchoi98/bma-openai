import assert from 'node:assert/strict';
import test from 'node:test';
import { Readable } from 'node:stream';
import { StudioStore, readBody, sha256 } from '../web/store.js';
import { Jobs } from '../web/jobs.js';
import { executeStudioJob, validateArtifacts } from '../web/worker.js';
import { createStudioApp } from '../web/server.js';
import { settingsFromEnv } from '../web/config.js';

// These tests call production modules. All AWS and model transports stay local.
const ACCOUNT = '123456789012';
const JOB = '11111111-1111-4111-8111-111111111111';
const OTHER = '22222222-2222-4222-8222-222222222222';
const NOW = Date.parse('2026-10-27T12:00:00.000Z');
const env = {
  APP_REGION: 'us-east-1', EXPECTED_ACCOUNT_ID: ACCOUNT, BMA_MODEL: 'openai.gpt-6-luna',
  BMA_RUNTIME_ARN: `arn:aws:bedrock-agentcore:us-east-1:${ACCOUNT}:runtime/studio_test`,
  BMA_SESSION_ROLE_ARN: `arn:aws:iam::${ACCOUNT}:role/StudioSessionRole`,
  STUDIO_BUCKET: 'studio-test-bucket', STUDIO_WORKER_ARN: `arn:aws:lambda:us-east-1:${ACCOUNT}:function:studio-worker`,
  APP_ACCESS_TOKEN: 'local-studio-test-access-token-1234567890',
};
const settings = settingsFromEnv(env);
const coded = code => error => error.code === code;
const scope = () => ({ account_id: ACCOUNT, app_region: 'us-east-1' });
const draft = (overrides = {}) => ({ request_id: JOB, notes: 'Original meeting notes', prompt: 'Prepare a report',
  outputs: ['docx'], style: 'business', language: 'en', ...overrides });

class MemoryS3 {
  constructor() { this.objects = new Map(); this.calls = []; this.version = 0; this.denied = new Set(); }
  seed(key, bytes) { this.objects.set(key, { bytes: Buffer.from(bytes), etag: `"v${++this.version}"` }); }
  seedJSON(key, value) { this.seed(key, JSON.stringify(value)); }
  async send(command) {
    const p = command.input, name = command.constructor.name;
    this.calls.push({ name, input: p });
    assert.equal(p.Bucket, settings.bucket, 'every storage operation is bucket bound');
    assert.equal(p.ExpectedBucketOwner, ACCOUNT, 'every storage operation is owner bound');
    if (name === 'GetObjectCommand') {
      if (this.denied.has(p.Key)) throw Object.assign(new Error('Denied'), { name: 'AccessDenied', $metadata: { httpStatusCode: 403 } });
      const value = this.objects.get(p.Key);
      if (!value) throw Object.assign(new Error('Missing'), { name: 'NoSuchKey' });
      return { ContentLength: value.bytes.length, ETag: value.etag, Body: Readable.from([Buffer.from(value.bytes)]) };
    }
    if (name === 'PutObjectCommand') {
      const old = this.objects.get(p.Key);
      if ((p.IfNoneMatch === '*' && old) || (p.IfMatch && old?.etag !== p.IfMatch)) {
        throw Object.assign(new Error('Conditional write conflict'), { $metadata: { httpStatusCode: 412 } });
      }
      assert.equal(p.ServerSideEncryption, 'AES256');
      this.seed(p.Key, p.Body);
      return { ETag: this.objects.get(p.Key).etag };
    }
    if (name === 'ListObjectsV2Command') {
      const keys = [...this.objects.keys()].filter(key => key.startsWith(p.Prefix)).sort();
      const start = p.ContinuationToken ? Number(p.ContinuationToken.slice(7)) : 0;
      const end = Math.min(keys.length, start + p.MaxKeys);
      return { Contents: keys.slice(start, end).map(Key => ({ Key })), IsTruncated: end < keys.length,
        ...(end < keys.length ? { NextContinuationToken: `offset:${end}` } : {}) };
    }
    throw new Error(`Unexpected fake transport command ${name}`);
  }
}
function fixture() {
  const client = new MemoryS3(), store = new StudioStore(settings, client), dispatches = [];
  let time = NOW;
  const clock = () => time;
  const jobs = new Jobs(settings, store, { clock, dispatch: async id => { dispatches.push(id); } });
  return { client, store, jobs, dispatches, clock, advance: delta => { time += delta; } };
}
async function addArtifact(f, id = JOB, overrides = {}) {
  const bytes = Buffer.from('PK\x03\x04local-office-fixture');
  const item = { id: 'report', filename: 'report.docx', key: `jobs/${id}/outputs/report.docx`,
    mime: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    size: bytes.length, sha256: sha256(bytes), kind: 'docx', title: 'Meeting report', ...overrides };
  if (item.key.startsWith(`jobs/${id}/outputs/`) && !item.key.includes('..')) await f.store.put(item.key, bytes, item.mime, null);
  await f.store.putJson(`jobs/${id}/artifacts.json`, { ...scope(), job_id: id, artifacts: [item], warnings: [] }, null);
  return { item, bytes };
}
class LocalBma {
  constructor(id = JOB, options = {}) {
    this.id = id; this.options = options; this.sessionId = 'local-session-' + id;
    this.posts = []; this.submissions = []; this.cancels = []; this.reads = []; this.hasInput = false;
    this.status = options.status || 'idle';
    this.session = { id: this.sessionId, agent: { model: settings.model, instructions: `[document-job:${id}]` },
      role_arn: settings.sessionRoleArn, environment: { runtime_arn: settings.runtimeArn } };
  }
  factory = () => this;
  async signed(method, path, payload) { return { url: path, options: { method, body: JSON.stringify(payload) } }; }
  fetch = async (url, options) => {
    if (url.endsWith('/events')) {
      await this.submitInput(this.sessionId, JSON.parse(options.body).events[0].input[0].content[0].text);
      return new Response(null, { status: 202 });
    }
    const result = await this.request(options.method, url, JSON.parse(options.body));
    return new Response(`data: ${JSON.stringify({ type: 'agent.session.created', session: { id: result.id } })}\n\n`);
  };
  async request(method, path, payload) {
    this.posts.push({ method, path, payload });
    assert.equal(method, 'POST'); assert.equal(path, '/openai/v1/agents/sessions');
    this.session = { ...this.session, ...payload, id: this.sessionId };
    if (payload.input && !this.options.submitLostBeforeRecord) this.hasInput = true;
    if (this.options.createLostResponse) throw new Error('Lost response after session creation');
    return { id: this.sessionId };
  }
  async listSessions() { return { data: this.options.noDiscoveredSession ? [] : [this.session], has_more: false }; }
  async getSession(id) {
    this.reads.push(id); assert.equal(id, this.sessionId);
    if (this.options.onRead) await this.options.onRead(this.reads.length);
    return { ...this.session, status: this.status, ...(this.options.wrongScope ? { role_arn: `arn:aws:iam::999999999999:role/Wrong` } : {}) };
  }
  async submitInput(id, text) {
    assert.equal(id, this.sessionId); this.submissions.push(text);
    if (this.options.submitLostBeforeRecord) throw new Error('No durable submission evidence');
    this.hasInput = true;
    if (this.options.submitLostAfterRecord) throw new Error('Lost submission response');
  }
  async listItems(id) {
    assert.equal(id, this.sessionId);
    if (this.options.incompleteHistory) return { complete: false, items: [] };
    if (!this.hasInput) return { complete: true, items: [] };
    const turn = 'turn-for-' + this.id;
    const items = [
      { id: 'user', type: 'message', role: 'user', turn_id: turn, content: [{ type: 'input_text', text: `[document-job:${this.id}]\nRequest` }] },
      { id: 'inspect', type: 'mcp_call', turn_id: turn, server_label: 'document_studio', name: 'inspect_inputs', status: 'completed', output: JSON.stringify({ structuredContent: { job_id: this.id, status: 'ok' } }) },
      { id: 'write', type: 'mcp_call', turn_id: turn, server_label: 'document_studio', name: 'create_documents', status: 'completed', output: { content: [{ type: 'text', text: JSON.stringify({ job_id: this.id, status: 'ok' }) }] } },
      { id: 'private-reasoning', type: 'message', role: 'assistant', turn_id: turn, channel: 'analysis', status: 'completed', content: [{ type: 'output_text', text: 'PRIVATE INTERNAL REASONING' }] },
      { id: 'answer', type: 'message', role: 'assistant', turn_id: turn, channel: 'final', phase: 'final_answer', status: 'completed', content: [{ type: 'output_text', text: 'Your report is ready.' }] },
    ];
    if (this.options.pendingTool) items.splice(2, 0, { id: 'pending', type: 'mcp_call', turn_id: turn,
      server_label: 'document_studio', name: 'create_chart', status: 'in_progress', output: 'not valid JSON yet' });
    if (this.options.otherTurn) items.push({ id: 'foreign', type: 'mcp_call', turn_id: 'another-turn',
      server_label: 'aws', name: 'delete_resources', status: 'completed', output: 'bad' },
      { type: 'message', role: 'assistant', turn_id: 'another-turn', status: 'completed', content: [{ type: 'output_text', text: 'OTHER TURN CONTENT' }] });
    if (this.options.badToolJob) items[1].output = { job_id: OTHER };
    if (this.options.badTool) items[1].name = 'list_aws_resources';
    return { complete: true, items };
  }
  async cancel(id) { assert.equal(id, this.sessionId); this.cancels.push(id); this.status = 'idle'; }
}
async function workerFixture(options = {}) {
  const f = fixture(); await f.jobs.create(draft()); await addArtifact(f);
  const bma = new LocalBma(JOB, options);
  const run = () => executeStudioJob(settings, f.store, JOB, { clock: f.clock, sleep: async () => {}, bmaFactory: bma.factory });
  return { ...f, bma, run };
}

test('configuration refuses a different model, region, account or unbound resource ARN', () => {
  assert.equal(settings.model, 'openai.gpt-6-luna');
  assert.equal(settingsFromEnv({ ...env, BMA_MODEL: 'openai.gpt-6.1-sol' }).model, 'openai.gpt-6.1-sol');
  for (const change of [{ APP_REGION: 'eu-west-1' }, { BMA_MODEL: 'other-model' }, { EXPECTED_ACCOUNT_ID: 'oops' },
    { BMA_RUNTIME_ARN: 'arn:aws:bedrock-agentcore:us-east-1:999999999999:runtime/other' },
    { BMA_SESSION_ROLE_ARN: 'arn:aws:iam::999999999999:role/Other' }, { APP_ACCESS_TOKEN: 'short' }]) {
    assert.throws(() => settingsFromEnv({ ...env, ...change }), coded('InvalidStudioConfiguration'));
  }
});

test('bounded body reader stops before consuming extra chunks and permits the exact boundary', async () => {
  assert.equal((await readBody(Readable.from(['ab', 'cd']), 4)).toString(), 'abcd');
  let consumed = 0, destroyed = false;
  const body = { destroy: () => { destroyed = true; }, async *[Symbol.asyncIterator]() { consumed++; yield 'abc'; consumed++; yield 'def'; consumed++; yield 'never read'; } };
  await assert.rejects(readBody(body, 5), coded('FileTooLarge'));
  assert.equal(consumed, 2); assert.equal(destroyed, true);
});

test('uploads preserve bytes, metadata hash and owner-bound encrypted writes; excessive data is not written', async () => {
  const f = fixture(), bytes = Buffer.from('name,value\n한글,42\n');
  const uploaded = await f.store.upload('report.csv', bytes);
  assert.deepEqual((await f.store.get(`uploads/${uploaded.id}/data`)).bytes, bytes);
  assert.equal((await f.store.uploadMeta(uploaded.id)).value.sha256, sha256(bytes));
  const before = f.client.objects.size;
  await assert.rejects(f.store.upload('huge.csv', Buffer.alloc(5242881)), coded('FileTooLarge'));
  await assert.rejects(f.store.upload('empty.csv', Buffer.alloc(0)), coded('FileTooLarge'));
  assert.equal(f.client.objects.size, before);
});

test('stored scope and record identity cannot redirect a job to another account or job', async () => {
  const f = fixture(); await f.jobs.create(draft());
  f.client.seedJSON(`jobs/${JOB}/input.json`, { ...scope(), id: OTHER });
  await assert.rejects(f.store.input(JOB));
  f.client.seedJSON(`jobs/${JOB}/input.json`, { ...scope(), id: JOB, account_id: '999999999999' });
  await assert.rejects(f.store.input(JOB), coded('StoredScopeMismatch'));
  const before = f.client.calls.length;
  await assert.rejects(f.store.get(`jobs/${JOB}/outputs/../../secret`), coded('InvalidObjectKey'));
  assert.equal(f.client.calls.length, before);
});

test('optimistic state updates retry a conflict against the newly committed state', async () => {
  const f = fixture(); await f.jobs.create(draft()); let first = true;
  const saved = await f.store.update(JOB, async current => {
    if (first) { first = false; const competing = await f.store.state(JOB); await f.store.putJson(`jobs/${JOB}/state.json`, { ...competing.value, count: 5 }, competing.etag); }
    return { ...current, count: (current.count || 0) + 1 };
  });
  assert.equal(saved.value.count, 6);
  await assert.rejects(f.store.update(JOB, current => ({ ...current, id: OTHER })), coded('ImmutableJobField'));
});

test('concurrent identical requests create one durable job and dispatch once; changed input conflicts', async () => {
  const f = fixture(); const [a, b] = await Promise.all([f.jobs.create(draft()), f.jobs.create(draft())]);
  assert.equal(a.job.id, JOB); assert.equal(b.job.id, JOB); assert.deepEqual(f.dispatches, [JOB]);
  assert.equal([...f.client.objects.keys()].filter(key => key.endsWith('/input.json')).length, 1);
  await assert.rejects(f.jobs.create(draft({ prompt: 'Different request' })), coded('RequestIdConflict'));
  assert.equal((await f.store.input(JOB)).value.prompt, 'Prepare a report');
});

test('revisions with omitted notes retain original notes and upload while preserving the original job', async () => {
  const f = fixture(); const upload = await f.store.upload('data.csv', Buffer.from('Month,Value\nJan,42'));
  await f.jobs.create(draft({ upload_id: upload.id }));
  await f.jobs.create({ request_id: OTHER, source_job_id: JOB, prompt: 'Use a presentation style', outputs: ['pptx'], style: 'presentation', language: 'ko' });
  const original = (await f.store.input(JOB)).value, revised = (await f.store.input(OTHER)).value;
  assert.equal(revised.notes, 'Original meeting notes'); assert.deepEqual(revised.upload, original.upload);
  assert.equal(revised.style, 'presentation'); assert.equal(revised.source_job_id, JOB);
  assert.equal(original.style, 'business'); assert.equal(original.prompt, 'Prepare a report');
  const notesOnly = fixture(); await notesOnly.jobs.create(draft());
  await notesOnly.jobs.create({ request_id: OTHER, source_job_id: JOB, prompt: 'Shorten it', outputs: ['docx'], style: 'business', language: 'en' });
  assert.equal((await notesOnly.store.input(OTHER)).value.notes, 'Original meeting notes');
});

test('request validation rejects excess source text, prompt, output lists and unknown fields before persistence', async () => {
  const f = fixture();
  const cases = [
    [{ notes: 'a'.repeat(50001) }, 'NotesTooLong'], [{ prompt: 'a'.repeat(4001) }, 'InvalidPrompt'],
    [{ outputs: [] }, 'InvalidOutputs'], [{ outputs: ['docx', 'docx'] }, 'InvalidOutputs'],
    [{ outputs: ['exe'] }, 'InvalidOutputs'], [{ session_id: 'foreign' }, 'InvalidRequest'],
    [{ style: 'unknown' }, 'InvalidStyle'], [{ language: 'xx' }, 'InvalidLanguage'],
    [{ request_id: '../wrong' }, 'InvalidIdentifier'], [{ notes: '   ' }, 'SourceRequired'],
  ];
  for (const [overrides, code] of cases) await assert.rejects(f.jobs.create(draft(overrides)), coded(code));
  assert.equal(f.client.objects.size, 0); assert.equal(f.dispatches.length, 0);
});

test('history pagination stays scoped and stale indexing cannot revert completed status', async () => {
  const f = fixture(); await f.jobs.create(draft()); const old = (await f.store.state(JOB)).value;
  f.advance(1000); await f.jobs.create(draft({ request_id: OTHER }));
  await f.store.update(JOB, value => ({ ...value, status: 'complete', phase: 'done', updated_at: new Date(NOW + 2000).toISOString() }));
  await f.store.index((await f.store.state(JOB)).value); await f.store.index(old);
  const first = await f.store.list({ limit: 1 });
  assert.equal(first.jobs[0].id, OTHER); assert.equal(first.complete, false);
  const second = await f.store.list({ limit: 1, cursor: first.next_cursor });
  assert.equal(second.jobs[0].id, JOB); assert.equal(second.jobs[0].status, 'complete'); assert.equal(second.complete, true);
  const forged = Buffer.from(JSON.stringify({ scope: 'other-bucket', token: 'offset:1' })).toString('base64url');
  await assert.rejects(f.store.list({ cursor: forged }), coded('InvalidCursor'));
});

test('access-denied object reads are absence only when an exact-prefix listing proves no object exists', async () => {
  const f = fixture(), key = `jobs/${JOB}/input.json`;
  f.client.denied.add(key); assert.equal(await f.store.get(key), null);
  f.client.seed(key, 'secret'); await assert.rejects(f.store.get(key), error => error.name === 'AccessDenied');
});

test('HTTP authentication runs before identity or storage work and applies upload/payload limits', { timeout: 15000 }, async () => {
  const f = fixture(); let identities = 0;
  const server = createStudioApp(settings, { store: f.store, jobs: f.jobs, identity: async () => { identities++; return ACCOUNT; } });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${server.address().port}`, auth = { Authorization: 'Bearer ' + settings.accessToken };
  try {
    assert.equal((await fetch(origin + '/api/config')).status, 401);
    assert.equal((await fetch(origin + '/api/config', { headers: { Authorization: 'Bearer wrong' } })).status, 401);
    assert.equal(identities, 0); assert.equal(f.client.calls.length, 0);
    const config = await (await fetch(origin + '/api/config', { headers: auth })).json();
    assert.equal(config.styles.length, 3); assert.equal(config.limits.fileBytes, 5242880);
    const uploaded = await fetch(origin + '/api/uploads', { method: 'POST', headers: { ...auth, 'Content-Type': 'application/octet-stream', 'X-File-Name': encodeURIComponent('분기.csv') }, body: Buffer.from('Month,Value\nJan,42') });
    assert.equal(uploaded.status, 201); assert.equal((await uploaded.json()).upload.name, '분기.csv');
    const huge = await fetch(origin + '/api/uploads', { method: 'POST', headers: { ...auth, 'X-File-Name': 'huge.csv' }, body: Buffer.alloc(5242881) });
    assert.equal(huge.status, 413);
    const unsupported = await fetch(origin + '/api/uploads', { method: 'POST', headers: { ...auth, 'X-File-Name': 'macro.xlsm' }, body: 'content' });
    assert.equal(unsupported.status, 422);
    const created = await fetch(origin + '/api/jobs', { method: 'POST', headers: { ...auth, 'Content-Type': 'application/json' }, body: JSON.stringify(draft()) });
    assert.equal(created.status, 202);
    const body = await created.json(); assert.equal(body.job.id, JOB);
    assert.doesNotMatch(JSON.stringify(body), /account_id|input_hash|worker_token|lease_until|session_role|arn:aws/);
    const badPayload = await fetch(origin + '/api/jobs', { method: 'POST', headers: { ...auth, 'Content-Type': 'application/json' }, body: JSON.stringify({ text: 'x'.repeat(262145) }) });
    assert.equal(badPayload.status, 413);
    const cancelled = await fetch(origin + `/api/jobs/${JOB}/cancel`, { method: 'POST', headers: { ...auth, 'Content-Type': 'application/json' }, body: '{}' });
    assert.equal(cancelled.status, 202); assert.equal((await f.store.state(JOB)).value.cancel_requested, true);
    assert.equal((await fetch(origin + `/api/jobs/${JOB}/cancel`, { method: 'POST', headers: { ...auth, 'Content-Type': 'application/json' }, body: '{"session":"other"}' })).status, 422);
  } finally { await new Promise(resolve => server.close(resolve)); }
});

test('artifact downloads return original bytes and reject corrupt or cross-job objects', async () => {
  const f = fixture(); await f.jobs.create(draft()); const { item, bytes } = await addArtifact(f);
  await f.store.update(JOB, value => ({ ...value, artifacts: [item], status: 'complete' }));
  assert.deepEqual((await f.jobs.artifact(JOB, item.id)).bytes, bytes);
  f.client.seed(item.key, 'tampered'); await assert.rejects(f.jobs.artifact(JOB, item.id), coded('ArtifactUnavailable'));
  await f.store.update(JOB, value => ({ ...value, artifacts: [{ ...item, key: `jobs/${OTHER}/outputs/report.docx` }] }));
  await assert.rejects(f.jobs.artifact(JOB, item.id), coded('ArtifactNotFound'));
});

test('artifact manifests reject traversal, cross-job keys, unsafe types, oversized files and excessive counts', () => {
  const item = { id: 'chart', filename: 'chart.svg', key: `jobs/${JOB}/outputs/chart.svg`, mime: 'image/svg+xml', size: 32, sha256: 'a'.repeat(64) };
  assert.equal(validateArtifacts({ job_id: JOB, artifacts: [item] }, JOB)[0].filename, 'chart.svg');
  for (const change of [{ filename: '../chart.svg' }, { filename: 'x..svg' }, { key: `jobs/${OTHER}/outputs/chart.svg` },
    { key: `jobs/${JOB}/outputs/../input.json` }, { mime: 'application/javascript' }, { size: 10485761 }, { size: 0 },
    { sha256: 'not-a-hash' }, { id: '../../secret' }]) {
    assert.throws(() => validateArtifacts({ job_id: JOB, artifacts: [{ ...item, ...change }] }, JOB), coded('InvalidArtifactManifest'));
  }
  assert.throws(() => validateArtifacts({ job_id: OTHER, artifacts: [item] }, JOB), coded('InvalidArtifactManifest'));
  assert.throws(() => validateArtifacts({ job_id: JOB, artifacts: Array.from({ length: 25 }, () => item) }, JOB), coded('InvalidArtifactManifest'));
});

test('a successful worker creates one job-bound session and submits once, even when invoked again', async () => {
  const f = await workerFixture(); const result = await f.run(); assert.equal(result.status, 'complete');
  assert.equal(result.answer, 'Your report is ready.'); assert.doesNotMatch(result.answer, /PRIVATE/);
  assert.deepEqual(result.completed_steps, ['reading', 'writing', 'packaging', 'done']);
  assert.equal((await f.run()).status, 'complete'); assert.equal(f.bma.posts.length, 1); assert.equal(f.bma.submissions.length, 1);
  const payload = f.bma.posts[0].payload;
  assert.equal(payload.role_arn, settings.sessionRoleArn); assert.equal(payload.agent.model, 'openai.gpt-6-luna');
  assert.equal(payload.environment.runtime_arn, settings.runtimeArn); assert.equal(payload.agent.tools.length, 1);
  assert.deepEqual(payload.agent.tools[0].allowed_tools, ['inspect_inputs', 'read_table', 'read_text', 'create_chart', 'create_diagram', 'create_documents']);
  assert.deepEqual(payload.agent.tools[0].transport.args, ['-m', 'studio.document_tools.mcp_server', '--job-id', JOB]);
  assert.equal(payload.input, undefined);
  assert.match(f.bma.submissions[0], /\[document-job:11111111-1111-4111-8111-111111111111\]/);
});

test('a live lease excludes another worker before it creates or cancels any session', async () => {
  const f = await workerFixture(); await f.store.update(JOB, value => ({ ...value, worker_token: 'other-worker', lease_until: new Date(NOW + 45000).toISOString() }));
  assert.equal((await f.run()).status, 'duplicate'); assert.equal(f.bma.posts.length, 0); assert.equal(f.bma.submissions.length, 0); assert.equal(f.bma.cancels.length, 0);
});

test('mismatched input identity is rejected before constructing a model client', async () => {
  let factoryCalls = 0;
  const store = { state: async () => ({ value: { id: JOB, status: 'queued' } }), input: async () => ({ value: { id: OTHER } }) };
  await assert.rejects(executeStudioJob(settings, store, JOB, { bmaFactory: () => { factoryCalls++; } }), coded('JobNotFound'));
  assert.equal(factoryCalls, 0);
});

test('a stored session from a different scope is not submitted to or cancelled', async () => {
  const f = await workerFixture({ wrongScope: true });
  await f.store.update(JOB, value => ({ ...value, bma_session_id: f.bma.sessionId, execution_stage: 'session_created' }));
  const result = await f.run(); assert.equal(result.status, 'uncertain'); assert.deepEqual(result.errors, ['SessionScopeMismatch']);
  assert.equal(f.bma.posts.length, 0); assert.equal(f.bma.submissions.length, 0); assert.equal(f.bma.cancels.length, 0);
});

test('pending tool output and other turns are ignored while final output remains usable', async () => {
  const f = await workerFixture({ pendingTool: true, otherTurn: true }); const result = await f.run();
  assert.equal(result.status, 'complete'); assert.equal(result.answer, 'Your report is ready.');
  assert.equal(result.completed_steps.includes('charting'), false); assert.deepEqual(result.errors, []);
});

test('completed tool output must belong to this job and only the document tool set is accepted', async () => {
  for (const options of [{ badToolJob: true }, { badTool: true }]) {
    const f = await workerFixture(options); const result = await f.run();
    assert.equal(result.status, 'failed'); assert.deepEqual(result.errors, ['ToolScopeViolation']);
    assert.equal(f.bma.submissions.length, 1);
  }
});

test('lost create response is reconciled without another creation POST', async () => {
  const f = await workerFixture({ createLostResponse: true });
  assert.equal((await f.run()).status, 'complete'); assert.equal(f.bma.posts.length, 1); assert.equal(f.bma.submissions.length, 1);
});

test('a submission without durable evidence becomes uncertain and is never posted again', async () => {
  const f = await workerFixture({ submitLostBeforeRecord: true }); const result = await f.run();
  assert.equal(result.status, 'uncertain'); assert.deepEqual(result.errors, ['SubmissionUncertain']);
  assert.equal((await f.run()).status, 'uncertain'); assert.equal(f.bma.posts.length, 1); assert.equal(f.bma.submissions.length, 1);
});

test('a persisted ambiguous session creation is reconciled without creating a new session', async () => {
  const f = await workerFixture({ noDiscoveredSession: true });
  await f.store.update(JOB, value => ({ ...value, execution_stage: 'creating_session' }));
  const result = await f.run(); assert.equal(result.status, 'uncertain'); assert.equal(f.bma.posts.length, 0); assert.equal(f.bma.submissions.length, 0);
});

test('resumed cancellation verifies and stops the existing owned session before reporting cancelled', async () => {
  const f = await workerFixture({ status: 'running' });
  await f.store.update(JOB, value => ({ ...value, status: 'running', bma_session_id: f.bma.sessionId,
    execution_stage: 'running', cancel_requested: true, lease_until: new Date(NOW - 1).toISOString(), worker_token: 'expired-worker' }));
  const result = await f.run(); assert.equal(result.status, 'cancelled');
  assert.deepEqual(f.bma.cancels, [f.bma.sessionId]); assert.ok(f.bma.reads.length >= 2);
  assert.equal(f.bma.posts.length, 0); assert.equal(f.bma.submissions.length, 0);
});

test('a worker losing ownership cannot cancel the replacement worker session', async () => {
  const f = await workerFixture({ status: 'running' });
  f.bma.options.onRead = async count => {
    if (count === 2) { await f.store.update(JOB, value => ({ ...value, worker_token: 'replacement-worker', lease_until: new Date(NOW + 45000).toISOString() })); throw new Error('Interrupted after ownership transfer'); }
  };
  const result = await f.run(); assert.equal(result.status, 'duplicate'); assert.equal(f.bma.cancels.length, 0);
  assert.equal((await f.store.state(JOB)).value.worker_token, 'replacement-worker');
});

test('cancellation before session creation and expired job budgets perform no model POST', async () => {
  const cancelled = await workerFixture(); await cancelled.store.update(JOB, value => ({ ...value, cancel_requested: true }));
  assert.equal((await cancelled.run()).status, 'cancelled'); assert.equal(cancelled.bma.posts.length, 0);
  const expired = await workerFixture(); expired.advance(300001);
  const result = await expired.run(); assert.equal(result.status, 'failed'); assert.deepEqual(result.errors, ['GenerationDeadlineExceeded']); assert.equal(expired.bma.posts.length, 0);
});

test('two simultaneous workers admit one session creation and one user submission', async () => {
  const f = await workerFixture(); const results = await Promise.all([f.run(), f.run()]);
  assert.deepEqual(results.map(result => result.status).sort(), ['complete', 'duplicate']);
  assert.equal(f.bma.posts.length, 1); assert.equal(f.bma.submissions.length, 1);
  assert.equal((await f.store.state(JOB)).value.status, 'complete');
});

test('terminal event snapshots expose usable files without internal state or storage identifiers', async () => {
  const f = await workerFixture(); await f.run();
  const events = [];
  for await (const event of f.jobs.events(JOB, new AbortController().signal)) events.push(event);
  assert.deepEqual(events.map(event => event.type), ['snapshot', 'complete']);
  assert.equal(events[1].job.status, 'complete'); assert.equal(events[1].job.artifacts[0].filename, 'report.docx');
  assert.doesNotMatch(JSON.stringify(events), /bma_session_id|bma_turn_id|worker_token|lease_until|input_hash|jobs\/.*\/outputs|account_id|arn:aws/);
});
