# infra Module

## Role
CloudFormation for the us-east-1 deployment. `bootstrap.yaml` (stack `bma-seoul-build`) creates the
code S3 bucket and ECR repository. `template.yaml` (stack `bma-seoul-inventory`) creates the app.

## Key Files
- `bootstrap.yaml` — `AWS::S3::Bucket` + policy (code ZIPs), `AWS::ECR::Repository` (`bma-seoul-runtime`); parameter `WebFunctionName`
- `template.yaml`
  - Roles: `RuntimeRole` (only role with Seoul read actions), `SessionRole` (model + Runtime invoke), `WebRole` (BMA, PassRole/AssumeRole, app state), `WorkerRole`
  - `Runtime` (`AWS::BedrockAgentCore::Runtime`, V2, HTTP), `WebFunction` / `WebRevision` / `WebEndpoint` (Lambda Web Functions), `InvestigationWorker` + `InvestigationWorkerAsync`
  - `AppState` S3 bucket + `AppStateTls` policy, `WebLogs` / `WorkerLogs`
  - Outputs: `WebUrl`, `RuntimeArn`, role ARNs, `InvestigationWorkerArn`, `StateBucket`, `ExpectedAccountId`, `AppRegion`, `TargetRegion`

## Rules
- Seoul read permissions belong to `RuntimeRole` only, scoped to the exact actions the tools call. Never attach `ReadOnlyAccess`.
- IAM changes must keep `tests/test_iam.py` and `tests/test_investigation_iam.py` passing; update `docs/api-iam.md`.
- Validate before deploying: `.venv/bin/cfn-lint infra/*.yaml`.
- Parameters come from `scripts/deployment_parameters.py` (writes a 0600 file under `artifacts/`); never commit parameter files or `AppAccessToken`.
- Do not use `--disable-rollback` for Web Revision replacements. Follow `docs/runbooks/deploy-production.md`.
- AI Document Studio has its own templates in `studio/infra/` (stacks `bma-office-build`, `bma-office-studio`); never add Studio resources or permissions to these templates.
