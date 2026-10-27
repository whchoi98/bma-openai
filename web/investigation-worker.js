import { STSClient, GetCallerIdentityCommand } from "@aws-sdk/client-sts";
import { S3Client } from "@aws-sdk/client-s3";
import { executeInvestigation } from "./investigation-executor.js";
import { S3InvestigationStore } from "./investigation-store.js";
import { S3Store } from "./stores.js";
import { settingsFromEnv } from "./settings.js";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const clientOptions = {
  region: "us-east-1", maxAttempts: 3,
  requestHandler: { requestTimeout: 10000, connectionTimeout: 3000 },
};
let clients;
const failure = (code) => Object.assign(new Error(code), { code });

function validateEvent(event) {
  if (!event || typeof event !== "object" || Array.isArray(event) ||
      Object.keys(event).some((key) => !["investigation_id", "run_id"].includes(key)) ||
      typeof event.investigation_id !== "string" || !uuid.test(event.investigation_id) ||
      typeof event.run_id !== "string" || !uuid.test(event.run_id)) throw failure("InvalidInvestigationEvent");
  return { investigation_id: event.investigation_id, run_id: event.run_id };
}

export function createInvestigationWorker({
  env = process.env, settings = settingsFromEnv(env, { requireAccessToken: false }),
  stsClient, s3Client, store, reportStore, execute = executeInvestigation,
} = {}) {
  const sts = stsClient || new STSClient(clientOptions);
  const s3 = s3Client || ((!store || !reportStore) ? new S3Client(clientOptions) : null);
  const investigationStore = store || new S3InvestigationStore(settings, s3);
  const reports = reportStore || new S3Store(settings, s3);
  return async (event) => {
    const ids = validateEvent(event);
    let accountId;
    try { accountId = (await sts.send(new GetCallerIdentityCommand({}))).Account; }
    catch { throw failure("AccountVerificationFailed"); }
    if (accountId !== settings.accountId) throw failure("AccountMismatch");
    return execute({ settings, store: investigationStore, reportStore: reports }, ids);
  };
}

export async function handler(event) {
  // Only SDK transports are reused between invocations; investigation state stays in S3.
  clients ||= { sts: new STSClient(clientOptions), s3: new S3Client(clientOptions) };
  return createInvestigationWorker({ stsClient: clients.sts, s3Client: clients.s3 })(event);
}
