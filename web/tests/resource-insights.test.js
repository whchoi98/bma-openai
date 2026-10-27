import assert from "node:assert/strict";
import test from "node:test";
import { topologyFromEvidence, securityFromEvidence } from "../resource-insights.js";
import samples from "../sample-data.json" with { type: "json" };

const result = (data, more = {}) => ({ tool: "get_vpc_topology", service: "vpc", status: "ok",
  pagination_complete: true, observed_at: "2026-10-27T00:00:00Z", data, ...more });

test("topology links only observed resources and reports missing references", () => {
  const graph = topologyFromEvidence([result([
    { id: "vpc-1", kind: "vpc" }, { id: "subnet-1", kind: "subnet", vpc_id: "vpc-1" },
    { id: "nat-1", kind: "nat_gateway", subnet_id: "subnet-missing" },
  ])]);
  assert.equal(graph.nodes.length, 3);
  assert.equal(graph.edges.length, 1);
  assert.equal(graph.edges[0].source, "vpc-1");
  assert.equal(graph.partial, true);
  assert.equal(graph.omitted, 1);
  assert.ok(!graph.nodes.find((n) => n.id === "subnet-missing"));
});

test("topology and checks preserve partial scope and never turn unknown into pass", () => {
  const source = result([
    { id: "vpc-1", kind: "vpc", security_checks: [{ id: "configured", status: "unknown", severity: "high" }] },
    { id: "subnet-1", kind: "subnet", vpc_id: "vpc-1" },
  ], { status: "partial", truncated: true, pagination_complete: false });
  assert.equal(topologyFromEvidence([source], 1).nodes.length, 1);
  assert.equal(topologyFromEvidence([source], 1).partial, true);
  assert.equal(securityFromEvidence([source]).checks[0].status, "unknown");
  assert.equal(securityFromEvidence([source]).partial, true);
});

test("actual EBS sample kind is included and attached only to observed instances", () => {
  const graph = topologyFromEvidence([samples.get_vpc_topology, samples.list_ec2_instances, samples.list_ebs_volumes]);
  assert.ok(graph.nodes.some((node) => node.kind === "ebs"));
  assert.ok(graph.edges.some((edge) => edge.relation === "attachment"));
});

test("failed topology detail keeps observed VPCs but marks the graph incomplete", () => {
  const graph = topologyFromEvidence([
    result([{ id: "vpc-1", kind: "vpc" }], { tool: "list_vpcs" }),
    result([], { status: "api_error", pagination_complete: false }),
  ]);
  assert.equal(graph.nodes.length, 1);
  assert.equal(graph.partial, true);
});
