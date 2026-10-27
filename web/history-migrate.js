import { pathToFileURL } from "node:url";
import { S3Client, ListObjectsV2Command } from "@aws-sdk/client-s3";
import { STSClient, GetCallerIdentityCommand } from "@aws-sdk/client-sts";
import { S3Store } from "./stores.js";
import { decodeHistoryCursor, encodeHistoryCursor, historyPrefix, validateRunId } from "./history.js";

const clientOptions = { maxAttempts: 3, requestHandler: { requestTimeout: 10000, connectionTimeout: 3000 } };
const validationErrors = new Set(["InvalidHistoryRecord", "InvalidHistoryTimestamp", "InvalidRunId",
  "HistoryAccountMismatch", "HistoryRegionMismatch", "HistoryModeMismatch", "HistoryScopeUnverified"]);

export async function migrateHistory(settings, { s3Client, stsClient, limit = 200, cursor } = {}) {
  historyPrefix(settings);
  if (settings.mode !== "live") throw new Error("HistoryMigrationRequiresLiveMode");
  if (!Number.isInteger(limit) || limit < 1 || limit > 200) throw new Error("InvalidMigrationLimit");
  if (!/^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$/.test(settings.stateBucket || "")) throw new Error("InvalidHistoryBucket");
  let token = decodeHistoryCursor("migration", cursor, settings);
  const sts = stsClient || new STSClient({ region: settings.appRegion, ...clientOptions });
  const identity = await sts.send(new GetCallerIdentityCommand({}));
  if (identity.Account !== settings.accountId) throw new Error("HistoryMigrationAccountMismatch");
  const client = s3Client || new S3Client({ region: settings.appRegion, ...clientOptions });
  const store = new S3Store(settings, client);
  const result = { scanned: 0, indexed: 0, skipped: [], next_cursor: null, complete: false };
  // Limit pages as well as records, including empty truncated pages.
  for (let pageCount = 0; pageCount < 10 && result.scanned < limit; pageCount++) {
    const maxKeys = Math.min(20, limit - result.scanned);
    const page = await client.send(new ListObjectsV2Command({
      Bucket: settings.stateBucket, Prefix: "runs/", MaxKeys: maxKeys, ExpectedBucketOwner: settings.accountId,
      ...(token ? { ContinuationToken: token } : {}),
    }));
    const objects = page.Contents || [];
    if (typeof page.IsTruncated !== "boolean" || !Array.isArray(objects) || objects.length > maxKeys ||
        (page.IsTruncated && (!page.NextContinuationToken || page.NextContinuationToken === token))) {
      throw new Error("InvalidHistoryPage");
    }
    for (const { Key } of objects) {
      result.scanned++;
      const match = typeof Key === "string" && /^runs\/([^/]+)\.json$/.exec(Key);
      let id;
      try { id = validateRunId(match?.[1]); }
      catch { result.skipped.push({ error: "InvalidRunId" }); continue; }
      let record;
      try { record = await store.get(id); }
      catch (error) {
        if (!validationErrors.has(error.message)) throw error;
        result.skipped.push({ id, error: error.message }); continue;
      }
      if (!record) { result.skipped.push({ id, error: "ReportNotFound" }); continue; }
      await store.writeHistoryIndex(record);
      result.indexed++;
    }
    result.complete = page.IsTruncated !== true;
    if (result.complete) { result.next_cursor = null; break; }
    token = page.NextContinuationToken;
    result.next_cursor = encodeHistoryCursor("migration", token, settings);
  }
  return result;
}

async function main(args) {
  if (args.length === 1 && args[0] === "--help") {
    console.log("Usage: node web/history-migrate.js [--limit 1..200] [--cursor TOKEN]\nRequires EXPECTED_ACCOUNT_ID and APP_STATE_BUCKET. Writes only scoped history indexes.");
    return;
  }
  const options = {};
  for (let i = 0; i < args.length; i += 2) {
    if (!["--limit", "--cursor"].includes(args[i]) || !args[i + 1]) throw new Error("InvalidMigrationArguments");
    const name = args[i].slice(2);
    if (name in options) throw new Error("InvalidMigrationArguments");
    options[name] = name === "limit" ? Number(args[i + 1]) : args[i + 1];
  }
  const settings = {
    mode: "live", accountId: process.env.EXPECTED_ACCOUNT_ID || "", stateBucket: process.env.APP_STATE_BUCKET || "",
    appRegion: process.env.APP_REGION || "us-east-1", targetRegion: process.env.TARGET_REGION || "ap-northeast-2",
  };
  console.log(JSON.stringify(await migrateHistory(settings, options), null, 2));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main(process.argv.slice(2)).catch((error) => {
    // Avoid printing SDK request bodies or account-bearing URLs in CLI output.
    const code = validationErrors.has(error.message) || /^(Invalid|History)/.test(error.message)
      ? error.message : "HistoryMigrationFailed";
    console.error(JSON.stringify({ error: code })); process.exitCode = 1;
  });
}
