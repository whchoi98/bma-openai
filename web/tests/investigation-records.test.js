import assert from "node:assert/strict";
import test from "node:test";
import { selectTurnItems, turnMarker, buildInvestigationReport, publicTurn, publicInvestigation,
  publicReport, scopeFields } from "../investigation-records.js";
import { getProcedure } from "../procedures.js";
import samples from "../sample-data.json" with { type: "json" };

const id = "11111111-2222-4333-8444-555555555555";
const previousId = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";
const settings = { mode: "sample", accountId: "000000000000", appRegion: "us-east-1", targetRegion: "ap-northeast-2", model: "" };
const procedure = { id: "inventory", version: "1.0.0", sha256: "a".repeat(64),
  name: { ko: "리소스 현황", en: "Resource inventory" }, steps: [] };
const session = { ...scopeFields(settings), id, procedure, turns: [{ id: previousId }, { id }] };
const turn = { ...scopeFields(settings), id, investigation_id: id, language: "ko", prompt: "방금 내용을 요약해 줘",
  created_at: "2026-10-27T00:00:00.000Z", answer: "확인한 범위입니다.", evidence: [], errors: [] };
const previousReport = (extra = {}) => ({ ...scopeFields(settings), id: previousId,
  investigation_id: id, evidence: [samples.get_account_context, samples.list_ec2_instances], ...extra });

test("current turn evidence is selected by its actual input and turn ID", () => {
  const items = [
    { id: "old", type: "message", role: "assistant", turn_id: "turn_old", content: [{ type: "output_text", text: "old" }] },
    { id: "input", type: "message", role: "user", turn_id: "turn_new", content: [{ type: "input_text", text: turnMarker(id) + "\nquestion" }] },
    { id: "new", type: "mcp_call", turn_id: "turn_new" },
    { id: "other", type: "mcp_call", turn_id: "turn_other" },
  ];
  const selected = selectTurnItems(items, id);
  assert.equal(selected.turnId, "turn_new");
  assert.deepEqual(selected.items.map((x) => x.id), ["input", "new"]);
  assert.equal(selectTurnItems(items, previousId), null);
});

test("duplicate accepted input and unprovable turn boundaries fail closed", () => {
  const input = { type: "message", role: "user", content: [{ type: "input_text", text: turnMarker(id) }] };
  assert.throws(() => selectTurnItems([{ ...input, id: "a", turn_id: "one" }, { ...input, id: "b", turn_id: "two" }], id),
    /DuplicateTurnInput/);
  assert.throws(() => selectTurnItems([{ ...input, id: "a" }], id), /MissingTurnIdentity/);
});

test("a follow-up with reused evidence preserves observation time and marks reuse in every report answer", () => {
  const previous = previousReport();
  const result = buildInvestigationReport(turn, session, settings, previous);
  assert.equal(result.evidence_reused, true);
  assert.deepEqual(result.source_run_ids, [previousId]);
  assert.equal(result.evidence[1].observed_at, previous.evidence[1].observed_at);
  assert.match(result.answer, /이전 조회 근거/);
  assert.equal(result.procedure.version, "1.0.0");
});

test("failed account evidence cannot be replaced by prior successful evidence", () => {
  const blocked = { ...samples.get_account_context, status: "account_mismatch", data: [] };
  const result = buildInvestigationReport({ ...turn, evidence: [blocked], errors: ["RuntimeAccountMismatch"] },
    session, settings, previousReport({ evidence: [samples.list_ec2_instances] }));
  assert.equal(result.evidence_reused, false);
  assert.equal(result.status, "failed");
  assert.deepEqual(result.evidence, [blocked]);
});

test("public snapshots cannot expose BMA IDs, lease data or internal session properties", () => {
  const safe = publicTurn({ ...turn, worker_token: "private", bma_turn_id: "turn_private",
    submission_text: "private", result: { ...turn, bma_session_id: "sess_private", status: "complete" } }, settings);
  assert.doesNotMatch(JSON.stringify(safe), /private/);
  assert.equal(safe.id, id);
});

test("public projections deeply strip internal fields while preserving legitimate prompt prose", () => {
  const snapshot = getProcedure("inventory");
  snapshot.name.private = "SECRET";
  snapshot.steps[0].bma_session_id = "SECRET";
  snapshot.steps[0].label.worker_token = "SECRET";
  const step = { ...snapshot.steps[0], status: "complete", lease_until: "SECRET" };
  const evidence = { ...samples.list_ec2_instances, item_id: "SECRET", reasoning: "SECRET",
    scope: { ...samples.list_ec2_instances.scope, reasoning: "SECRET" },
    data: samples.list_ec2_instances.data.map((row) => ({ ...row, raw_model_item: "SECRET" })) };
  const report = { ...turn, procedure: snapshot, procedure_steps: [step], evidence: [evidence] };
  const value = publicTurn({ ...turn, prompt: "Explain the reasoning for this result.",
    procedure_steps: [step], evidence: [evidence], result: report }, settings);
  assert.doesNotMatch(JSON.stringify(value), /SECRET|raw_model_item|"skills"|"markdown"|"item_id"/);
  assert.equal(value.prompt, "Explain the reasoning for this result.");
  assert.equal(value.result.procedure.id, "inventory");
  assert.equal(value.procedure_steps[0].status, "complete");
  assert.doesNotMatch(JSON.stringify(publicInvestigation({ ...session, procedure: snapshot }, settings)), /SECRET|"skills"/);
  value.result.procedure.name.en = "changed";
  assert.notEqual(snapshot.name.en, "changed");
});

test("public evidence rejects foreign scope and objects inside scalar fields", () => {
  for (const extra of [
    { account_id: "999988887777" }, { region: "us-west-2" }, { mode: "live" },
    { data: [{ ...samples.list_ec2_instances.data[0], account_id: "999988887777" }] },
    { data: [{ ...samples.list_ec2_instances.data[0], id: { reasoning: "SECRET" } }] },
    { scope: { cluster: { bma_session_id: "SECRET" } } },
  ]) assert.throws(() => publicTurn({ ...turn, evidence: [{ ...samples.list_ec2_instances, ...extra }] }, settings),
    /Mismatch|Invalid/);
  assert.throws(() => publicReport({ ...turn, account_id: "999988887777" }, settings), /Mismatch/);
  assert.throws(() => publicTurn({ ...turn, evidence: [samples.list_ec2_instances] }), /Settings|Scope/);
});

test("all registered sample evidence retains its valid nested public observations", () => {
  const evidence = Object.values(samples);
  const result = publicTurn({ ...turn, evidence }, settings);
  assert.deepEqual(result.evidence, evidence);
});

test("reuse requires a same-scope earlier turn from this investigation", () => {
  for (const extra of [
    { investigation_id: previousId }, { account_id: "999988887777" }, { app_region: "us-west-2" },
    { target_region: "us-west-2" }, { mode: "live" }, { id },
    { id: "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff" },
    { source_run_ids: ["bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"] },
    { evidence: [{ ...samples.list_ec2_instances, account_id: "999988887777" }] },
  ]) assert.throws(() => buildInvestigationReport(turn, session, settings, previousReport(extra)), /Previous|Mismatch/);
  assert.throws(() => buildInvestigationReport(turn, { ...session, turns: [{ id }, { id: previousId }] },
    settings, previousReport()), /Previous/);
});

test("cancelled uncertain and failed runs use the report status schema without reusing successful history", () => {
  for (const status of ["cancelled", "uncertain", "failed"]) {
    const result = buildInvestigationReport({ ...turn, status }, session, settings, previousReport());
    assert.equal(result.status, "failed");
    assert.equal(result.evidence_reused, false);
    assert.ok(result.errors.length);
    assert.deepEqual(result.evidence, []);
    assert.deepEqual(result.source_run_ids, []);
    const observed = buildInvestigationReport({ ...turn, status, evidence: [samples.list_ec2_instances] },
      session, settings, previousReport());
    assert.equal(observed.status, status === "failed" ? "failed" : "partial");
    assert.ok(observed.errors.length);
  }
});

test("incomplete observation flags cannot become a complete report", () => {
  for (const extra of [
    { truncated: true }, { pagination_complete: false }, { errors: [{ code: "AccessDenied" }] },
    { missing_resource_ids: ["i-missing"] },
  ]) {
    const result = buildInvestigationReport({ ...turn,
      evidence: [{ ...samples.list_ec2_instances, ...extra }] }, session, settings);
    assert.equal(result.status, "partial");
  }
});

test("successfully observed no-data metrics preserve empty evidence without implying an incomplete query", () => {
  const evidence = [samples["get_resource_metrics:sample-idle"]];
  const result = buildInvestigationReport({ ...turn, evidence }, session, settings);
  assert.equal(result.status, "complete");
  assert.equal(result.evidence[0].data[0].data_status, "no_data");
  assert.deepEqual(result.evidence[0].data[0].points, []);
});
