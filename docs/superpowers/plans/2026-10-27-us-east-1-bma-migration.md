# us-east-1 BMA migration

**Goal:** Remove this project's us-west-2 deployment and redeploy the existing
AWS Operations Desk in us-east-1 using the regional Mantle model
`openai.gpt-6-luna` through BMA. Seoul remains the resource query region.

**Authorization:** The user's 2026-10-27 instruction explicitly authorizes
deletion of the old deployment and deployment in us-east-1. Scope is limited to
the resources proven to belong to the two project stacks and their Runtime/BMA
sessions. Other applications and Seoul resources must remain untouched.

**Execution:** Apply the plan inline with review after each task. The workspace
has no Git repository, so preserve source and deployment evidence in local
artifacts rather than creating a branch or commit.

## Constraints

- `APP_REGION=us-east-1`, `TARGET_REGION=ap-northeast-2`.
- `AGENT_BACKEND=bma`, `BMA_MODEL=openai.gpt-6-luna`.
- STS must match the existing deployment-verified account before every
  deployment, migration or cleanup operation.
- Keep 24 allowlisted MCP tools, four Skills, scoped read-only IAM, explicit SDK
  regions, masked output, Korean/English UI, Markdown/HTML/Office reports.
- Preserve the upstream Runtime lifecycle server unchanged.
- Use BMA public text-delta SSE events; never expose internal reasoning.
- Keep live limits at two resources, two pages and one hour.
- The source repository `/home/ec2-user/my-project/awsops` remains read-only.
- Archive old deployment metadata and report objects locally before deletion.
  Do not relabel historical Oregon observations as Virginia observations.
- No mutations of the queried EC2, RDS, ECS, Lambda or other Seoul resources.

## Task 1: Verify and record the migration boundary

- [x] Read the existing deployment manifest and verify STS identity.
- [x] Inventory exact physical resources in `bma-seoul-build` and
  `bma-seoul-inventory`; verify these stacks are absent in us-east-1.
- [x] Read the us-east-1 Mantle model catalog and resolve the requested name to
  `openai.gpt-6-luna`.
- [x] Preserve source, reports, stack metadata and project session IDs.
- [x] Validate BMA model acceptance with the selected regional model.

## Task 2: Adapt and verify the application

Files: `infra/`, `aws_inventory/config.py`, `aws_inventory/sample.py`,
`runtime/Dockerfile`, `web/settings.js`, `web/history.js`, `web/runners.js`,
`web/reports.js`, `web/office-reports.js`, `web/ui/i18n.js`, `webapp/`,
`scripts/`, `.env.example`, `tests/`, `web/tests/`.

- [x] Add regression coverage for east-region signing, Seoul-only resource
  clients, west-region rejection and BMA model/report metadata.
- [x] Update deployment defaults, ARN validation and region labels to
  us-east-1; keep the target region immutable.
- [x] Include BMA model/backend/processing-scope metadata in final results.
- [x] Grant the global Converse policy only when the Converse backend is
  selected; BMA deployment must use only its regional Mantle model permission.
- [x] Regenerate the Skills/sample contract and browser bundle.
- [x] Run the Python and Node suites, template validation and container check.

## Task 3: Remove the old deployment

- [x] Cancel/delete only BMA sessions linked to the old project Runtime.
- [x] Delete the main stack and wait for deletion.
- [x] Delete the bootstrap stack and wait for deletion.
- [x] Empty/delete the two exact retained buckets, including object versions;
  delete the exact retained ECR repository and Runtime log groups.
- [x] Verify the old stacks, Web Function, Runtime, roles, buckets, repository
  and project log groups are absent. Save the cleanup evidence.

## Task 4: Deploy in us-east-1

- [x] Create the bootstrap stack, push the rebuilt ARM64 Runtime image and
  upload the rebuilt Web Function ZIP.
- [x] Generate private parameters using the unchanged deployment account and
  application access key.
- [x] Deploy the main stack with the BMA backend and regional Luna model.
- [x] Check stack completion, Runtime readiness, active Web endpoint and
  actual deployed environment variables without printing secrets.

## Task 5: Validate and document

- [x] Exercise BMA -> Runtime -> MCP -> Seoul AWS APIs with bounded queries;
  verify real request IDs, error handling and public SSE text deltas.
- [x] Verify the actual browser's region/model labels, masking, languages,
  themes, resource graph, history, HTML preview and report downloads.
- [x] Update the active manifest, README and deployment/data-flow documents;
  preserve historical validation records as historical.
- [x] Package the final source and record cleanup and deployment results.
