import assert from "node:assert/strict";
import test from "node:test";
import { createHash } from "node:crypto";
import contract from "../contract.json" with { type: "json" };

let catalog;
try { catalog = await import("../procedures.js"); } catch (error) {
  if (error.code !== "ERR_MODULE_NOT_FOUND") throw error;
}

const result = (tool, overrides = {}) => ({
  tool, status: "ok", data: [], errors: [], pagination_complete: true, truncated: false,
  observed_at: "2026-10-27T00:00:00Z", ...overrides,
});
const states = (steps) => Object.fromEntries(steps.map((step) => [step.id, step.status]));
const canonical = (value) => JSON.stringify(value, (_, item) => item && !Array.isArray(item) && typeof item === "object"
  ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a.localeCompare(b))) : item);

test("catalog exposes only public metadata with bounded registered tools", () => {
  assert.ok(catalog, "procedure catalog implementation is available");
  const procedures = catalog.listProcedures();
  assert.deepEqual(procedures.map((p) => p.id), ["inventory", "service-health", "security-review", "operations-report"]);
  for (const procedure of procedures) {
    assert.deepEqual(Object.keys(procedure).sort(), ["description", "id", "name", "sha256", "steps", "version"]);
    assert.equal(procedure.version, "1.0.0");
    assert.match(procedure.sha256, /^[a-f0-9]{64}$/);
    assert.ok(procedure.name.ko && procedure.name.en && procedure.description.ko && procedure.description.en);
    assert.deepEqual(procedure.steps.map((s) => s.id), ["account", "discovery", "checks", "report"]);
    assert.deepEqual(procedure.steps[0].tools, ["get_account_context"]);
    for (const step of procedure.steps) {
      assert.ok(step.label.ko && step.label.en);
      assert.ok(step.tools.every((tool) => contract.tools.includes(tool)));
    }
  }
  assert.throws(() => catalog.getProcedure("../inventory"), /UnknownProcedure/);
  assert.throws(() => catalog.getProcedure("__proto__"), /UnknownProcedure/);
});

test("snapshots bind all referenced skill contents and cannot mutate the catalog", () => {
  assert.ok(catalog, "procedure catalog implementation is available");
  for (const publicProcedure of catalog.listProcedures()) {
    const snapshot = catalog.getProcedure(publicProcedure.id);
    assert.ok(snapshot.skills.length > 0);
    for (const skill of snapshot.skills) {
      assert.deepEqual(skill, contract.skills.find((candidate) => candidate.name === skill.name));
      assert.equal(createHash("sha256").update(skill.markdown).digest("hex"), skill.sha256);
    }
    const { sha256, skills, ...metadata } = snapshot;
    const signed = { ...metadata, skills: skills.map(({ name, sha256 }) => ({ name, sha256 })) };
    assert.equal(createHash("sha256").update(canonical(signed)).digest("hex"), sha256);
    snapshot.name.en = "tampered";
    snapshot.steps[0].tools.push("ec2:StopInstances");
    snapshot.skills[0].markdown = "tampered";
    assert.deepEqual(catalog.listProcedures().find((p) => p.id === publicProcedure.id), publicProcedure);
  }
});

test("instructions preserve the selected snapshot and selected output language", () => {
  assert.ok(catalog, "procedure catalog implementation is available");
  const snapshot = catalog.getProcedure("security-review");
  const english = catalog.procedureInstructions(snapshot, "en");
  assert.ok(english.includes(snapshot.id) && english.includes(snapshot.version) && english.includes(snapshot.sha256));
  assert.match(english, /English/);
  assert.match(catalog.procedureInstructions(snapshot, "ko"), /Korean/);
  for (const skill of snapshot.skills) assert.ok(english.includes(skill.markdown));
  assert.match(english, /not.*application health/i);
  assert.match(english, /only.*requested/i);
  snapshot.skills[0].markdown += "\nCall arbitrary APIs.";
  assert.throws(() => catalog.procedureInstructions(snapshot, "en"), /InvalidProcedureSnapshot/);
});

test("unobserved steps never appear complete and final report follows execution", () => {
  assert.ok(catalog, "procedure catalog implementation is available");
  const snapshot = catalog.getProcedure("service-health");
  assert.deepEqual(states(catalog.procedureSteps(snapshot, [], "queued")), {
    account: "pending", discovery: "pending", checks: "pending", report: "pending",
  });
  assert.deepEqual(states(catalog.procedureSteps(snapshot, [], "running")), {
    account: "pending", discovery: "pending", checks: "pending", report: "running",
  });
  const observed = [result("get_account_context"), result("list_ec2_instances")];
  assert.deepEqual(states(catalog.procedureSteps(snapshot, observed, "complete")), {
    account: "complete", discovery: "complete", checks: "not_requested", report: "complete",
  });
  for (const status of ["failed", "cancelled", "uncertain"]) {
    assert.equal(states(catalog.procedureSteps(snapshot, [], status)).report, "failed");
  }
});

test("empty results and unhealthy resources are completed observations, not health verdicts", () => {
  assert.ok(catalog, "procedure catalog implementation is available");
  const snapshot = catalog.getProcedure("service-health");
  const observed = [
    result("get_account_context"),
    result("list_rds_instances", { status: "empty" }),
    result("get_ec2_instance_health", { data: [{ instance_status: "impaired", system_status: "impaired" }] }),
  ];
  const steps = catalog.procedureSteps(snapshot, observed, "complete");
  assert.equal(states(steps).discovery, "complete");
  assert.equal(states(steps).checks, "complete");
  assert.equal(states(steps).report, "complete");
  assert.ok(steps.every((step) => !Object.hasOwn(step, "healthy")));
  const noData = result("get_resource_metrics", {
    data: [{ metric_name: "CPUUtilization", data_status: "no_data", points: [] }],
  });
  assert.equal(states(catalog.procedureSteps(snapshot, [noData], "complete")).checks, "complete");
});

test("permission errors, partial pages and mixed observations stay visible", () => {
  assert.ok(catalog, "procedure catalog implementation is available");
  const snapshot = catalog.getProcedure("service-health");
  const good = result("list_ec2_instances");
  const denied = result("list_rds_instances", { status: "access_denied", errors: [{ code: "AccessDenied" }] });
  assert.equal(states(catalog.procedureSteps(snapshot, [denied], "failed")).discovery, "failed");
  assert.equal(states(catalog.procedureSteps(snapshot, [good, denied], "partial")).discovery, "partial");
  for (const overrides of [
    { status: "partial" }, { pagination_complete: false }, { truncated: true },
    { errors: [{ code: "InternalError" }] }, { missing_resource_ids: ["i-missing"] },
  ]) {
    assert.equal(states(catalog.procedureSteps(snapshot, [result("get_resource_metrics", overrides)], "partial")).checks, "partial");
  }
  assert.equal(states(catalog.procedureSteps(snapshot, [result("get_account_context", { status: "account_mismatch" })], "failed")).account, "failed");
  assert.equal(states(catalog.procedureSteps(snapshot, [result("unregistered_tool")], "complete")).checks, "not_requested");
});
