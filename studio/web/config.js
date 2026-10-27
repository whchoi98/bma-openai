export const LIMITS = Object.freeze({
  fileBytes: 5 * 1024 * 1024, notesCharacters: 50000, promptCharacters: 4000,
  rows: 10000, columns: 50, cells: 100000, sheets: 5, visualAssets: 6,
  slides: 12, outputBytes: 10 * 1024 * 1024, turnSeconds: 300,
});
export const STYLES = Object.freeze([
  { id: "business", name: { ko: "업무 보고서", en: "Business report" },
    description: { ko: "정돈된 표와 명확한 요약으로 전달합니다.", en: "Clear summaries and structured tables." } },
  { id: "aws-desk", name: { ko: "AWS 운영 데스크", en: "AWS Operations Desk" },
    description: { ko: "네이비와 청록, 나눔스퀘어의 익숙한 스타일입니다.", en: "Navy, teal and familiar NanumSquare typography." } },
  { id: "presentation", name: { ko: "발표 자료", en: "Presentation" },
    description: { ko: "핵심 문장과 큰 시각 자료에 집중합니다.", en: "Key messages and prominent visuals." } },
]);
export const FORMATS = Object.freeze(["pptx", "docx", "chart", "diagram"]);
export const TOOLS = Object.freeze(["inspect_inputs", "read_table", "read_text", "create_chart", "create_diagram", "create_documents"]);
export const TERMINAL = new Set(["complete", "partial", "failed", "cancelled", "uncertain"]);
export const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export const error = (code, httpStatus = 422) => Object.assign(new Error(code), { code, httpStatus });
export function validId(value) {
  if (typeof value !== "string" || !uuidPattern.test(value)) throw error("InvalidIdentifier");
  return value;
}
export function settingsFromEnv(env = process.env, { worker = false } = {}) {
  const settings = {
    appRegion: env.APP_REGION || "us-east-1", accountId: env.EXPECTED_ACCOUNT_ID || "",
    model: env.BMA_MODEL || "openai.gpt-6-luna", runtimeArn: env.BMA_RUNTIME_ARN || "",
    sessionRoleArn: env.BMA_SESSION_ROLE_ARN || "", bucket: env.STUDIO_BUCKET || "",
    workerArn: env.STUDIO_WORKER_ARN || "", accessToken: env.APP_ACCESS_TOKEN || "",
    maxTurnSeconds: 300,
  };
  if (settings.appRegion !== "us-east-1" ||
      !["openai.gpt-6-luna", "openai.gpt-6.1-sol", "openai.gpt-6.1-terra"].includes(settings.model) ||
      !/^\d{12}$/.test(settings.accountId)) throw error("InvalidStudioConfiguration", 500);
  if (!new RegExp(`^arn:aws:bedrock-agentcore:us-east-1:${settings.accountId}:runtime/[A-Za-z0-9_-]+$`).test(settings.runtimeArn) ||
      !new RegExp(`^arn:aws:iam::${settings.accountId}:role/[A-Za-z0-9_+=,.@/-]+$`).test(settings.sessionRoleArn) ||
      !/^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$/.test(settings.bucket)) throw error("InvalidStudioConfiguration", 500);
  if (!worker && (settings.accessToken.length < 32 ||
      !new RegExp(`^arn:aws:lambda:us-east-1:${settings.accountId}:function:[A-Za-z0-9_-]+$`).test(settings.workerArn))) {
    throw error("InvalidStudioConfiguration", 500);
  }
  return Object.freeze(settings);
}
export function publicJob(value) {
  const keys = ["id", "title", "prompt", "created_at", "updated_at", "status", "phase", "completed_steps",
    "style", "language", "outputs", "source_job_id", "upload", "answer", "profile", "artifacts", "warnings", "errors"];
  const result = Object.fromEntries(keys.filter((key) => value[key] !== undefined).map((key) => [key, value[key]]));
  result.artifacts = (value.artifacts || []).map(({ id, filename, mime, kind, size, title }) =>
    ({ id, filename, mime, kind, size, title }));
  return result;
}
