# Report history and Office extraction

> 이 문서는 최초 설계 또는 오레곤 추출 검증 기록을 포함합니다. 현재 실행 리전과 모델은 [배포 보고서](aws-deployment.md)를 기준으로 확인합니다.

Implemented from the original `/home/ec2-user/my-project/awsops` source on
2026-10-27. Source files were read as text; the original application was not
executed or changed.

## Provenance

| Original file | SHA-256 | Adaptation |
| --- | --- | --- |
| `src/lib/report-docx.ts` | `95b4f8621136bdc1389ce55f62c490ac776807b0ce4b2f19a615deebebaf0629` | Adapted `classifyLine`, `parseInline`, `buildHeading`, `buildParagraph`, `buildTable`, section conversion, document styles and page footer into `web/office-reports.js`. |
| `src/lib/report-pptx.ts` | `023ff5720a85172953fa9c0d5f18c587dea15f996112b866399b267fc69a1027` | Adapted Markdown classification, inline stripping, line-width estimation, overflow splitting, title/footer composition and in-memory `write` output. Korean glyph widths and a fixed slide budget replace the original large layout planner. |
| `src/lib/report-generator.ts` | `a2877c641185b7ffb504cdd38c54b3b048ecb1c52c672a3a14ce1e4ccbb218ce` | Adapted the `jsonBlock` evidence presentation idea. Complete saved evidence is retained; `abbreviate`, SQL collectors, cost data, model calls and diagnosis scores were not imported. |
| `src/lib/resource-inventory.ts` | `01b12323cbf6d4b5ac4b80ad1faf15a567afc420114603de924f71fa943bd204` | Adapted account-scoped history and time-keyed snapshots into S3 report indexes. The local filesystem, rolling deletion, aggregate snapshots, trend calculations and swallowed read failures were not imported. |

The original source package declares `docx ^9.6.1` and `pptxgenjs ^4.0.1`.
This application pins `docx 9.6.1` and `pptxgenjs 4.0.1`; tests use
`jszip 3.10.1`. The coordinator's `image-size 2.0.4` override was present
when the generated Office files were tested.

## Store and history interfaces

```js
new MemoryStore(settings);
new S3Store(settings, optionalS3Client);
await store.put(record);
await store.get(uuid); // record or null only for an absent record
await store.list({ limit: 10, cursor });
// { runs: [publicSummary, ...], next_cursor: string | null, complete: boolean }
```

`settings` supplies `accountId`, `appRegion=us-west-2`,
`targetRegion=ap-northeast-2`, `mode` and, for S3, `stateBucket`.
`MemoryStore()` without settings retains the sample-mode default and the
existing twenty-record retention limit. Stored and loaded memory records
are cloned.

`web/history.js` exports:

| Helper | Contract |
| --- | --- |
| `validateHistoryRecord(record, settings)` | Returns the record after validating ID, UTC date, account, target region, mode and evidence scope; otherwise throws. |
| `summarizeHistoryRecord(record, settings)` | Produces the public, redacted list summary. |
| `historyPrefix(settings)` | Fixed `history/<account>/<target-region>/` prefix. |
| `historyIndexKey(record, settings)` | Prefix plus thirteen-digit reverse timestamp, UUID and `.json`. |
| `reportServiceScope(record)` | Saved supported/requested scope plus observed queried/unqueried service names. |
| `reportCoverage(record)` | Query-result and completeness counts, independent of page completeness. |
| `reportAccountIds(record, accountIds)` | Collects supplied identities, structured account/owner IDs and ARN account components. |
| `redactReportValue(value, accounts, options)` | Copies values with the existing presentation masks, including object keys and numeric known identities. |

New server records persist trusted top-level `account_id`, `app_region`,
`target_region`, `supported_services` and, when available,
`requested_services`. Legacy records without top-level scope can load only
when their saved evidence proves the configured account and target region.
Evidence-less legacy failures have no provable owner and are rejected.
New failures with trusted top-level scope can be saved without evidence.
Blocked foreign-account identity evidence is accepted only with empty
resource data, no successful non-STS call and trusted top-level scope.
It does not establish a successful resource query.

Public summaries include the masked account, original UTC and converted
KST creation time, prompt excerpt, execution status, service scope,
per-tool status/scope/pagination flags, coverage counts and errors.
Strict masking also covers known account digits embedded in names and
object keys. The validated top-level report UUID remains intact as an
opaque routing key so history entries can still be loaded.
They contain neither resource rows nor the full answer. Prompt excerpts
are capped at 320 characters; scope entries exceeding 4,096 bytes are
replaced with an explicit truncation marker. `summary_truncated` records
either condition. A failed query does not become a zero-resource result.

Observed CloudWatch metric API calls add `cloudwatch` to queried scope.
The original resource service is retained: a VPC result using EC2 APIs
counts as `vpc`, not as an EC2 instance inventory.

S3 records remain under `runs/<uuid>.json`, capped at 4,000,000 bytes.
Separate indexes are capped at 128,000 bytes and carry internal identity
fields plus the public summary. All requests set `ExpectedBucketOwner`.
Writes retain explicit `AES256` server-side encryption.

Index names use `9999999999999 - Date.parse(created_at)` so ordinary S3
lexicographic ordering is newest first, with UUIDs breaking timestamp
ties. `list` accepts integer limits from 1 to 20 and makes one bounded
`ListObjectsV2` request plus at most twenty index reads. It never scans
`runs/`. Cursor envelopes are checked against a digest of the configured
account/target-region prefix, app region, execution mode and store kind.
S3 and migration cursors also bind the state bucket, so a cursor cannot
be reused against another bucket. Memory cursors do not require a bucket.
The prefix always comes from trusted settings.

The page's `complete` means the index listing is exhausted.
`summary.coverage.complete` separately describes the saved query.
Corrupt pages/indexes, missing listed indexes, access denial and other
read errors are surfaced, not converted into an empty history.

If the full record write succeeds but the index write fails, `put`
throws an error with `name` and `code` set to `HistoryIndexWriteFailed`
and `recordSaved=true`. Its `cause` retains the original SDK error.
The report remains retrievable by ID; the server can distinguish this
case from a failed report write.

## Bounded migration

```sh
# Use the existing deployment account, bucket and AWS credential environment.
node web/history-migrate.js --limit 200

# Continue only when the previous output returned next_cursor.
node web/history-migrate.js --limit 200 --cursor '<next_cursor>'
```

Required environment: `EXPECTED_ACCOUNT_ID`, `APP_STATE_BUCKET`.
`APP_REGION` defaults to `us-west-2` and `TARGET_REGION` defaults to
`ap-northeast-2`; other regions are rejected. Runtime ARN, model and app
access-token environment variables are not needed.

`migrateHistory(settings, { s3Client, stsClient, limit, cursor })` is the
testable implementation. It verifies `sts:GetCallerIdentity` before any
S3 access, scans at most 200 old records and ten listing pages per
invocation, validates each record, and calls
`S3Store.writeHistoryIndex(record)`. This operation writes only the
corresponding index. No original record is edited or deleted.

The result contains `scanned`, `indexed`, explicit `skipped` reasons,
`next_cursor` and `complete`. Unverified or mismatched legacy records are
reported in `skipped`; S3 failures stop the migration. A continuation
cursor always remains scoped to `runs/` in the same configured account
and bucket. Repeating a migration is idempotent for unchanged records.

Required permission boundaries for coordinator integration:

| Principal | Read/list | Write |
| --- | --- | --- |
| Web Function | Existing `runs/*` get; scoped history-index get; bucket list restricted to `history/<account>/ap-northeast-2/` | Existing `runs/*` put and scoped history-index put |
| Migration operator | `sts:GetCallerIdentity`; `runs/*` get; bucket list restricted to `runs/` | Scoped history-index put |

Neither path requires object deletion or a query against inventoried
resources. The Web Function does not need the migration's `runs/`
listing permission.

## Office exports

```js
import { renderOfficeReport, OFFICE_MIME } from "./office-reports.js";

const bytes = await renderOfficeReport(record, "docx", {
  accountIds: [settings.accountId],
});
// bytes is a Buffer; OFFICE_MIME.docx and OFFICE_MIME.pptx are exact MIME types.
```

Exports are generated entirely from the saved record. They make no AWS,
model, image-fetch or external-content calls.

Identity masking precedes Markdown parsing and separation into Office
formatting runs. It covers formatted account numbers, ARNs, known numeric
identities, keys, literal account digits embedded in resource names, and
interrupted account prefixes in failed reports.
Passing the configured account in `accountIds` is essential when a failed
legacy record has no identity evidence. Full account IDs remain internal;
public summaries and Office content show only the final three digits.
The validated top-level report UUID is preserved in Office metadata/notes;
resource-row IDs and ARNs are still subject to strict account masking.

Both formats retain original UTC timestamps, KST display conversions,
saved service scope, query completeness, errors and evidence. Narrative
cleanup reuses `cleanMarkdownProse`; resource IDs and JSON evidence are
not rewritten as prose. All authored text styles use `NanumSquare`,
including Word's East Asian font setting. Font files are not embedded in
Office documents; a reader without NanumSquare may substitute a font.

DOCX contains readable headings, paragraphs, tables, the answer, errors
and the complete redacted evidence JSON. PPTX contains bounded readable
summaries, with the complete redacted answer, errors and evidence in the
final Evidence slide's speaker notes. Truncated presentation sections
explicitly state the omitted display-line count and direct readers to
those notes.

Limits are exported as `OFFICE_LIMITS`: 1,000,000 input JSON bytes,
4,000,000 output bytes and forty slides. DOCX also rejects more than
20,000 generated content elements. Oversized exports fail with
`OfficeReportTooLarge` rather than returning a silently incomplete file.
Unsupported formats fail with `UnsupportedOfficeFormat`.

## Validation

```sh
node --test web/tests/history.test.js web/tests/office-reports.test.js
node web/history-migrate.js --help
```

The thirty scoped tests cover pagination, fixed prefixes,
cross-account/region/mode and cross-bucket cursor rejection, legacy scope, blocked identity
evidence, explicit incomplete results, index-only migration limits,
partial persistence, S3 error propagation, size limits, both languages,
Office redaction and presentation truncation. They also check embedded
account digits in names/keys and loading valid UUIDs that resemble account
numbers, including the default sample MemoryStore.

Generated ZIP entries are inspected with JSZip. Every XML and relationship
entry is parsed using Python 3's standard-library XML parser. Tests
assert preservation of UTC/KST, API names, error codes, evidence and font
styles, and inspect slide notes as well as visible content. Local XML
validation requires subprocess support; the sandbox's `spawnSync`
restriction required an authorized unsandboxed test run.

No live AWS or deployment validation was performed by this extraction
task. The coordinator owns integrated IAM, routes, UI, deployment and
bounded live validation.

The integrated Node regression run also passed all 58 tests at the time
of this handoff. The four original source hashes were rechecked and
remained unchanged.
