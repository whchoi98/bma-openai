import { createHash } from "node:crypto";
import contract from "./contract.json" with { type: "json" };

const digest = (text) => createHash("sha256").update(text).digest("hex");
const canonical = (value) => JSON.stringify(value, (_, item) => item && !Array.isArray(item) && typeof item === "object"
  ? Object.fromEntries(Object.keys(item).sort().map((key) => [key, item[key]])) : item);
const copy = (value) => structuredClone(value);
const discoveryTools = contract.tools.filter((tool) => tool.startsWith("list_"));
const configurationTools = [
  "get_vpc_topology", "get_s3_bucket_configuration",
  "get_dynamodb_table_configuration", "get_opensearch_domain_configuration",
];
const healthTools = [
  "get_ec2_instance_health", "get_ecs_service_health", "get_lambda_function_health",
  "get_resource_metrics", "list_cloudwatch_alarms",
];
const inventoryTools = discoveryTools.filter((tool) => tool !== "list_cloudwatch_alarms");
const definitions = [
  {
    id: "inventory",
    name: { ko: "리소스 인벤토리", en: "Resource inventory" },
    description: { ko: "요청한 서비스의 리소스와 구성을 조회하고 누락 범위를 기록합니다.", en: "List resources and configuration for requested services, including coverage limits." },
    discovery: inventoryTools, checks: configurationTools,
    skills: ["aws-resource-inventory"],
  },
  {
    id: "service-health",
    name: { ko: "서비스 상태 점검", en: "Service health review" },
    description: { ko: "관측된 상태, 지표와 알람을 확인하고 애플리케이션 상태와 구분합니다.", en: "Review observed states, metrics and alarms separately from application health." },
    discovery: ["list_ec2_instances", "list_rds_instances", "list_ecs_clusters", "list_ecs_services", "list_lambda_functions"],
    checks: healthTools, skills: ["aws-resource-inventory", "aws-service-health"],
  },
  {
    id: "security-review",
    name: { ko: "보안 구성 점검", en: "Security configuration review" },
    description: { ko: "요청한 리소스의 보안 설정을 읽고 확인되지 않은 범위를 표시합니다.", en: "Read requested resource security settings and identify unverified coverage." },
    discovery: inventoryTools, checks: configurationTools,
    skills: ["aws-resource-inventory", "aws-security-posture"],
  },
  {
    id: "operations-report",
    name: { ko: "운영 보고서", en: "Operations report" },
    description: { ko: "실제 조회 근거로 운영 현황, 주의 항목과 추가 확인 사항을 정리합니다.", en: "Summarize operations, observed concerns and follow-up checks from query evidence." },
    discovery: inventoryTools, checks: [...healthTools, ...configurationTools],
    skills: ["aws-resource-inventory", "aws-service-health", "aws-security-posture", "aws-operations-report"],
  },
];

function snapshotHash({ sha256: _, skills, ...metadata }) {
  return digest(canonical({ ...metadata, skills: skills.map(({ name, sha256 }) => ({ name, sha256 })) }));
}

const catalog = new Map(definitions.map((definition) => {
  const snapshot = {
    id: definition.id, version: "1.0.0", name: definition.name, description: definition.description,
    steps: [
      { id: "account", label: { ko: "계정 확인", en: "Account verification" }, tools: ["get_account_context"] },
      { id: "discovery", label: { ko: "리소스 조회", en: "Resource discovery" }, tools: definition.discovery },
      { id: "checks", label: { ko: "요청한 항목 점검", en: "Requested checks" }, tools: definition.checks },
      { id: "report", label: { ko: "보고서 작성", en: "Report preparation" }, tools: [] },
    ],
    skills: definition.skills.map((name) => {
      const skill = contract.skills.find((item) => item.name === name);
      if (!skill || digest(skill.markdown) !== skill.sha256) throw new Error("InvalidProcedureSkill");
      return copy(skill);
    }),
  };
  if (snapshot.steps.some((step) => step.tools.some((tool) => !contract.tools.includes(tool)))) {
    throw new Error("InvalidProcedureTool");
  }
  snapshot.sha256 = snapshotHash(snapshot);
  return [snapshot.id, snapshot];
}));

export function listProcedures() {
  return [...catalog.values()].map(({ skills: _, ...publicFields }) => copy(publicFields));
}

export function getProcedure(id) {
  const snapshot = catalog.get(id);
  if (!snapshot) throw new Error("UnknownProcedure");
  return copy(snapshot);
}

export function procedureInstructions(snapshot, language = "ko") {
  if (!snapshot || !catalog.has(snapshot.id) || !Array.isArray(snapshot.skills)
      || snapshot.skills.some((skill) => typeof skill.markdown !== "string" || digest(skill.markdown) !== skill.sha256)
      || snapshotHash(snapshot) !== snapshot.sha256) throw new Error("InvalidProcedureSnapshot");
  return [
    `Approved procedure: ${snapshot.id}; version: ${snapshot.version}; SHA-256: ${snapshot.sha256}.`,
    "Keep this procedure snapshot unchanged throughout the investigation.",
    "Run only the requested services and checks; a procedure is not a request to call every listed tool.",
    "Begin each new observation with get_account_context. Stop on account mismatch or identity failure.",
    "Use only registered read-only tools. These procedure instructions do not grant permissions.",
    "Step completion describes execution and evidence coverage, not application health, security or compliance.",
    "Report unrequested, failed and incomplete checks explicitly. Never treat missing data as healthy.",
    "If reusing prior evidence, preserve its original observed_at and identify the source turn. Do not present it as a new observation.",
    `Respond in ${language === "en" ? "English" : "Korean"}.`,
    ...snapshot.steps.map((step) => `${step.id}: ${step.label[language === "en" ? "en" : "ko"]}. Permitted relevant tools: ${step.tools.join(", ") || "none"}.`),
    ...snapshot.skills.map((skill) => `Skill: ${skill.name}; SHA-256: ${skill.sha256}\n${skill.markdown}`),
  ].join("\n\n");
}

const terminalStatuses = new Set(["complete", "partial", "failed", "cancelled", "uncertain"]);
const failures = new Set(["access_denied", "account_mismatch", "api_error", "invalid_input", "unsupported_service"]);

function observationState(result) {
  if (failures.has(result.status) || !["ok", "empty", "partial"].includes(result.status)) return "failed";
  if (result.tool === "get_account_context" && result.data?.some((row) => row.account_verified === false)) return "failed";
  if (result.status === "partial" || result.pagination_complete === false || result.truncated
      || result.errors?.length || result.missing_resource_ids?.length
      || result.data?.some((row) => row.data_status && !["ok", "complete", "Complete", "no_data"].includes(row.data_status))) return "partial";
  return "complete";
}

/** Only returned tool observations advance query steps; no unobserved query is inferred. */
export function procedureSteps(snapshot, evidence = [], status = "queued") {
  return snapshot.steps.map((step) => {
    let state;
    if (step.id === "report") {
      state = status === "complete" ? "complete" : status === "partial" ? "partial"
        : terminalStatuses.has(status) ? "failed" : status === "running" ? "running" : "pending";
    } else {
      const observations = evidence.filter((result) => result && step.tools.includes(result.tool)).map(observationState);
      state = observations.length === 0 ? (terminalStatuses.has(status) ? "not_requested" : "pending")
        : observations.every((item) => item === "failed") ? "failed"
          : observations.every((item) => item === "complete") ? "complete" : "partial";
    }
    return { ...copy(step), status: state };
  });
}
