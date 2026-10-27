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
  - `WebDistribution` (CloudFront, `PriceClass_All`) and `WebOriginAccessControl` (`lambda`, `sigv4`, `always-amz-auth`); inline public/private TTL and `ForwardedValues`, no new CachePolicy resources
  - Outputs: `WebUrl` (CloudFront), `OriginWebUrl` (regional origin), `DistributionId`, `OriginAccessControlId`, `RuntimeArn`, role ARNs, `InvestigationWorkerArn`, `StateBucket`, `ExpectedAccountId`, `AppRegion`, `TargetRegion`

## Rules
- Seoul read permissions belong to `RuntimeRole` only, scoped to the exact actions the tools call. Never attach `ReadOnlyAccess`.
- IAM changes must keep `tests/test_iam.py` and `tests/test_investigation_iam.py` passing; update `docs/api-iam.md`.
- Validate before deploying: `.venv/bin/cfn-lint infra/*.yaml`.
- Parameters come from `scripts/deployment_parameters.py` (writes a 0600 file under `artifacts/`); never commit parameter files or `AppAccessToken`.
- Do not use `--disable-rollback` for Web Revision replacements. Follow `docs/runbooks/deploy-production.md`.
- AI Document Studio has its own templates in `studio/infra/` (stacks `bma-office-build`, `bma-office-studio`); never add Studio resources or permissions to these templates.
- Final `WebEndpointAuthType` is `IamAuth`. The CloudFront deployer retains the existing auth type during prepare, binds the exact distribution/endpoint resource policy, then changes auth during cutover.
- Web Function resource policies are managed by `scripts/deploy_cloudfront.py` through `put_resource_policy`, separately from CFN. Keep the original policy backup and revision-aware updates; never add an unrestricted CloudFront principal.
- Default behavior TTLs stay `0/0/0` with origin `no-store`. Forward Authorization and required upload/SSE headers, cookies and query strings, but never viewer Host. Only `/` and `/static/*` may cache public content; no compression for dynamic SSE.
- The account's custom cache-policy quota was full during this rollout. Do not delete unrelated policies or silently replace the inline configuration. Run `tests/test_cloudfront.py` and both HTTP cache-control suites for changes; see `docs/runbooks/cloudfront-oac.md`.
