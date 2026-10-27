import contract from "./contract.json" with { type: "json" };
const pick = (object, keys) => Object.fromEntries(keys.filter((key) => Object.hasOwn(object, key)).map((key) => [key, object[key]]));

function decode(value) {
  for (let i = 0; i < 4; i++) {
    if (typeof value === "string") {
      if (value.length > 1_000_000) throw new Error("ToolResultTooLarge");
      value = JSON.parse(value);
    } else if (value?.structuredContent) value = value.structuredContent;
    else if (Array.isArray(value?.content)) value = value.content.filter((c) => c.type === "text").map((c) => c.text).join("\n");
    else break;
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("InvalidToolResult");
  return value;
}

export function sanitizeResult(value, settings, tool) {
  if (value.tool !== tool || !contract.statuses.includes(value.status) || !Array.isArray(value.data) || !Array.isArray(value.api_calls)) throw new Error("InvalidToolResult");
  if (value.region !== settings.targetRegion) throw new Error("EvidenceRegionMismatch");
  if (value.mode !== settings.mode) throw new Error("EvidenceModeMismatch");
  if (value.account_id !== settings.accountId) {
    const blocked = value.status === "account_mismatch" && value.data.length === 0;
    const identityFailed = value.account_id === null && value.data.length === 0 && value.api_calls.some((c) => c.api === "GetCallerIdentity" && c.success === false);
    if (!blocked && !identityFailed) throw new Error("EvidenceAccountMismatch");
  }
  if (value.data.length > 100 || value.api_calls.length > 31) throw new Error("ToolResultTooLarge");
  const result = pick(value, contract.top_fields);
  result.data = value.data.map((row) => {
    const safe = pick(row, contract.data_fields);
    if (safe.points) safe.points = safe.points.slice(0, 1440).map((p) => pick(p, ["timestamp", "value"]));
    if (safe.deployments) safe.deployments = safe.deployments.slice(0, 10).map((p) => pick(p,
      ["id", "status", "rollout_state", "desired_count", "running_count", "pending_count", "created_at", "updated_at"]));
    if (safe.security_checks) safe.security_checks = safe.security_checks.slice(0, 20)
      .filter((c) => c && ["pass", "fail", "unknown"].includes(c.status)).map((c) => pick(c, ["id", "status", "severity"]));
    if (safe.ingress_rules) safe.ingress_rules = safe.ingress_rules.slice(0, 50).map((r) => pick(r,
      ["protocol", "from_port", "to_port", "source_type", "source", "unrestricted"]));
    for (const key of ["subnet_ids", "security_group_ids", "attached_instance_ids"]) {
      if (safe[key]) safe[key] = safe[key].slice(0, 100).filter((v) => typeof v === "string").map((v) => v.slice(0, 256));
    }
    return safe;
  });
  result.api_calls = value.api_calls.map((c) => pick(c, ["service", "api", "region", "success", "duration_ms", "request_id", "retry_attempts"]));
  result.errors = (value.errors || []).map((e) => pick(e, ["code", "service", "api", "kind", "resource_id"]));
  return result;
}

export function publicItems(items, settings) {
  const answers = [], evidence = [], errors = [], seen = new Set();
  for (const item of items) {
    if (!item || typeof item !== "object") continue;
    if (item.id && seen.has(item.id)) continue;
    if (item.id) seen.add(item.id);
    if (item.type === "message" && item.role === "assistant" && [undefined, null, "final"].includes(item.channel)) {
      for (const content of item.content || []) if (content.type === "output_text" && typeof content.text === "string") answers.push(content.text.slice(0, 40_000));
    }
    if (item.type === "mcp_call" && item.server_label === "seoul_aws" && contract.tools.includes(item.name)) {
      try { evidence.push({ ...sanitizeResult(decode(item.output ?? item.result), settings, item.name), item_id: item.id }); }
      catch (error) {
        errors.push(["EvidenceAccountMismatch", "EvidenceRegionMismatch", "EvidenceModeMismatch", "ToolResultTooLarge"].includes(error.message) ? error.message : "InvalidToolResult");
      }
    }
  }
  return { answer: answers.join("\n\n").slice(0, 60_000), evidence, evidence_errors: errors };
}
