# AI Document Studio implementation plan

Specification: `studio/README.md`. User requested a nondeveloper office
creation demo with BMA/GPT, optional separate Web Function, all three design
styles, real progress messages/animation and downloadable files.

Preserve the existing AWS Operations Desk deployment. Use a separate Web
Function, document Runtime, worker and private data bucket in us-east-1.
Deployed model: openai.gpt-6.1-sol. The user's later guidance authorized
evaluating Sol or Terra when Luna struggled. A Luna document asset-reference
failure led to selecting Sol, which passed all three live styles.
No new AWS resource-query permissions.

- [x] Implement bounded XLSX/CSV/text parsing, profiling and exact chart aggregation.
- [x] Implement three document styles, chart/diagram renderers and PPTX/DOCX/HTML.
- [x] Implement office-worker UI with real progress, previews and downloads.
- [x] Implement job-bound MCP, authenticated upload/job APIs and worker.
- [x] Add isolated CloudFormation stacks and build/deployment tooling.
- [x] Review input, concurrency, permissions, output and browser safety.
- [x] Run parser/renderer/backend/browser tests, inspect generated artifacts.
- [x] Deploy separately and verify real BMA file-to-chart and note-to-Office flows.
- [x] Document limits/data flow and package final source and validation results.

Evidence: `artifacts/studio/summary.json`, `artifacts/studio/final-state.json`,
`artifacts/studio/bma-proof.json`, and `artifacts/studio/iam-live.json`.
Usage and limits: `docs/document-studio.md`.
Source archive: `artifacts/studio/source.zip`; integrity and deployed-code
comparison: `artifacts/studio/final-package-proof.json`.
