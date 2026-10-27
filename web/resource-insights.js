// Adapted relationship semantics from awsops/src/app/topology/page.tsx and queries/relationships.ts.
// Edges describe observed configuration references, not tested network reachability.
const KINDS = new Set(["vpc", "subnet", "security_group", "route_table", "internet_gateway",
  "nat_gateway", "vpc_endpoint", "ec2", "ebs", "rds"]);

export function topologyFromEvidence(evidence, maximum = 100) {
  const resources = new Map();
  let partial = false, omitted = 0;
  for (const result of evidence || []) {
    if (result.truncated || !result.pagination_complete || !["ok", "empty"].includes(result.status)) partial = true;
    if (!["ok", "partial", "empty"].includes(result.status)) continue;
    for (const source of result.data || []) {
      const rawKind = source.kind || ({ list_ec2_instances: "ec2", list_ebs_volumes: "ebs", list_rds_instances: "rds" })[result.tool];
      const kind = ({ ebs_volume: "ebs" })[rawKind] || rawKind;
      if (!KINDS.has(kind) || typeof source.id !== "string") continue;
      if (!resources.has(source.id) && resources.size >= maximum) { omitted++; partial = true; continue; }
      resources.set(source.id, {
        ...(resources.get(source.id) || {}), ...source, kind,
        source_tool: result.tool, observed_at: result.observed_at,
      });
    }
  }
  const edges = new Map();
  const connect = (source, target, relation) => {
    if (!source || source === target) return;
    if (!resources.has(source) || !resources.has(target)) { omitted++; partial = true; return; }
    const key = `${source}:${target}:${relation}`;
    edges.set(key, { id: key, source, target, relation });
  };
  for (const node of resources.values()) {
    connect(node.vpc_id, node.id, "vpc");
    connect(node.subnet_id, node.id, "subnet");
    for (const id of node.subnet_ids || []) connect(id, node.id, "subnet");
    for (const id of node.security_group_ids || []) connect(id, node.id, "security_group");
    for (const id of node.attached_instance_ids || []) connect(id, node.id, "attachment");
    if (node.relationships_truncated || node.attachments_truncated) partial = true;
  }
  return { nodes: [...resources.values()], edges: [...edges.values()], partial, omitted };
}

export function securityFromEvidence(evidence) {
  const findings = new Map();
  let partial = false;
  for (const result of evidence || []) {
    if (result.truncated || !result.pagination_complete || result.errors?.length) partial = true;
    for (const row of result.data || []) {
      for (const check of row.security_checks || []) {
        if (typeof check.id !== "string" || !["pass", "fail", "unknown"].includes(check.status)) continue;
        const key = `${result.service}:${row.id}:${check.id}`;
        findings.set(key, {
          key, service: result.service, resource_id: row.id, check_id: check.id,
          status: check.status, severity: check.severity, observed_at: result.observed_at, source_tool: result.tool,
        });
      }
    }
  }
  return { checks: [...findings.values()], partial };
}
