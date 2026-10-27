# BMA investigation implementation plan

**Goal:** Add continuing BMA investigations, reconnect recovery and a versioned
operations procedure catalog to the existing Virginia deployment.
**Spec:** `docs/superpowers/specs/2026-10-27-bma-investigations.md`
**Architecture:** A bounded Lambda Event Function owns each BMA turn; S3 conditional
records coordinate work and hold public progress. Web SSE delivers snapshots.
**Tech Stack:** Node.js 24, existing React/Markdown, AWS SDK v3, S3, BMA REST, Lambda.

The user's feature request follows the recommended three features. Proceed within
that scope and the existing deployment authorization. Do not add comparison reports.
There is no Git repository; use the baseline source ZIP and a task ledger.

## Interfaces and ownership

1. Storage agent owns `web/investigation-store.js` and its test only.
   Exports `MemoryInvestigationStore(settings)`, `S3InvestigationStore(settings, client?)`,
   `InvestigationConflict`, `investigationPrefix(settings)`.
   Methods: `getSession(id)`/`getTurn(id)` -> `{value,etag}|null`;
   `createSession(value)`/`createTurn(value)` -> `{value,etag}`;
   `putSession(value,etag)`/`putTurn(value,etag)` -> `{value,etag}`;
   `list({limit=10,cursor}={})` -> `{investigations,next_cursor,complete}`.
   Session writes also maintain the bounded list index. A failed index write reports
   `recordSaved=true` and does not silently claim success.
2. Catalog agent owns `web/procedures.js`, `web/tests/procedures.test.js`,
   `infra/template.yaml`, `infra/bootstrap.yaml` and relevant new IAM tests.
   Exports `listProcedures()`, `getProcedure(id)` (throws on unknown),
   `procedureInstructions(snapshot,language)`, `procedureSteps(snapshot,evidence,status)`.
   Snapshot fields match the spec; add `skills:[{name,sha256,markdown}]` internally.
   Worker Lambda name is `${StackName}-investigation-worker`, handler
   `investigation-worker.handler`, same ZIP/CodeBucket/CodeKey/CodeVersionId as Web,
   nodejs24.x, arm64, 512 MB, timeout 360, reserved concurrency 2.
   Web env `INVESTIGATION_WORKER_ARN`; worker needs no APP_ACCESS_TOKEN.
3. UI agent owns `web/ui/investigations.js`, `web/ui/app.js`, `web/ui/i18n.js`,
   `webapp/static/index.html`, `webapp/static/style.css`.
   Match HTTP/SSE contracts in the spec. Preserve the single-question flow and
   existing exported report rendering. Store only last investigation ID in localStorage.
4. Root owns BMA client extensions, investigation service/worker/routes,
   worker settings, integration tests, build/deployment and final docs.

## Tasks

- [x] Implement and test conditional investigation storage, scope and list cursors.
- [x] Implement procedure snapshots and observed step state; narrow worker IAM and Lambda.
- [x] Implement worker leases, BMA session reuse, bounded turn streaming and final records.
- [x] Add authenticated investigation APIs and snapshot SSE without cancellation on disconnect.
- [x] Add investigation UI, procedure selection, continuing turns and reconnect behavior.
- [x] Review independent changes and run regression, concurrency and recovery tests.
- [x] Build and update the existing us-east-1 stack without replacing Runtime or deleting data.
- [x] Verify live BMA continuation, browser reconnect, two languages and exports.
- [x] Update docs, package source and record final evidence.

## Acceptance boundaries

Every production module receives behavioral tests before completion. POST ambiguity
must never trigger an unexamined repeat model input. The existing query Runtime keeps
exactly 24 tools and the same Seoul IAM. No secrets/raw reasoning may appear in public
snapshots or browser storage. Live deployment remains `openai.gpt-6-luna`, us-east-1,
target ap-northeast-2, two resources/two pages/one hour.
