export function settingsFromEnv(env = process.env, { requireAccessToken = true } = {}) {
  const mode = env.DATA_MODE || "live";
  const agentBackend = env.AGENT_BACKEND || "bma";
  const settings = {
    mode, accountId: mode === "sample" ? "000000000000" : (env.EXPECTED_ACCOUNT_ID || ""),
    appRegion: env.APP_REGION || "us-east-1", targetRegion: env.TARGET_REGION || "ap-northeast-2",
    agentBackend,
    model: agentBackend === "converse" ? (env.CONVERSE_MODEL || "global.openai.gpt-6-luna") : (env.BMA_MODEL || ""),
    runtimeArn: env.BMA_RUNTIME_ARN || "", sessionRoleArn: env.BMA_SESSION_ROLE_ARN || "",
    accessToken: env.APP_ACCESS_TOKEN || "", stateBucket: env.APP_STATE_BUCKET || "",
    investigationWorkerArn: env.INVESTIGATION_WORKER_ARN || "",
    maxResources: Number(env.MAX_RESOURCES || 100), maxPages: Number(env.MAX_PAGES || 10),
    maxMetricHours: Number(env.MAX_METRIC_HOURS || 6), maxDatapoints: Number(env.MAX_DATAPOINTS || 1440),
    maxTurnSeconds: Number(env.MAX_TURN_SECONDS || 180),
  };
  if (!["sample", "live"].includes(mode)) throw new Error("DATA_MODE must be sample or live.");
  if (!["bma", "converse"].includes(agentBackend)) throw new Error("Invalid AGENT_BACKEND.");
  if (settings.appRegion !== "us-east-1" || settings.targetRegion !== "ap-northeast-2") throw new Error("Invalid demo Regions.");
  if (settings.investigationWorkerArn &&
      !new RegExp(`^arn:aws:lambda:us-east-1:${settings.accountId}:function:[A-Za-z0-9_-]{1,64}$`).test(settings.investigationWorkerArn)) {
    throw new Error("Invalid investigation worker ARN.");
  }
  for (const [key, max] of [["maxResources", 100], ["maxPages", 10], ["maxMetricHours", 6], ["maxDatapoints", 1440], ["maxTurnSeconds", 600]]) {
    if (!Number.isInteger(settings[key]) || settings[key] < 1 || settings[key] > max) throw new Error(`Invalid ${key}.`);
  }
  if (mode === "live") {
    if (!/^\d{12}$/.test(settings.accountId) || settings.accountId === "000000000000") throw new Error("EXPECTED_ACCOUNT_ID is required.");
    if (!new RegExp(`^arn:aws:bedrock-agentcore:us-east-1:${settings.accountId}:runtime/[A-Za-z0-9_-]+$`).test(settings.runtimeArn)) throw new Error("Invalid Runtime ARN.");
    if (!new RegExp(`^arn:aws:iam::${settings.accountId}:role/[A-Za-z0-9_+=,.@/-]+$`).test(settings.sessionRoleArn)) throw new Error("Invalid session role ARN.");
    if (agentBackend === "converse" && settings.model !== "global.openai.gpt-6-luna") throw new Error("Unsupported Converse model.");
    if (agentBackend === "bma" && !/^openai\.[A-Za-z0-9._-]+$/.test(settings.model)) throw new Error("BMA_MODEL is required.");
    if (requireAccessToken && settings.accessToken.length < 32) throw new Error("APP_ACCESS_TOKEN must contain at least 32 characters.");
    if (!/^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$/.test(settings.stateBucket)) throw new Error("APP_STATE_BUCKET is required.");
  }
  return Object.freeze(settings);
}
