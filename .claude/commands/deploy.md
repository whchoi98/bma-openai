---
description: Build and deploy the us-east-1 stacks following docs/runbooks/deploy-production.md
allowed-tools: Read, Glob, Bash(git status:*), Bash(git branch:*), Bash(.venv/bin/python -m pytest:*), Bash(npm test --prefix web:*), Bash(npm run build --prefix web:*), Bash(.venv/bin/cfn-lint:*), Bash(docker build:*)
---

# Deploy

Build and deploy the application. This changes the real AWS account in `artifacts/deployment-context.json`.
Commands that push images, upload code or deploy stacks are intentionally NOT pre-allowed: each one must be
approved by the user when prompted.

## Step 1: Pre-Deploy Checks

1. Verify working tree is clean: `git status`
2. Verify current branch (warn if not `main`)
3. Run tests: `.venv/bin/python -m pytest`, `npm test --prefix web`, `.venv/bin/cfn-lint infra/*.yaml`
4. Confirm the runbook exists: `docs/runbooks/deploy-production.md`
5. Ask the user for the release version (new immutable ECR tag) and whether this is a Runtime image, Web ZIP, or full update

## Step 2: Follow Runbook

Follow `docs/runbooks/deploy-production.md` step by step:
- `scripts/preflight.py` (account + model list) → `scripts/export_web_contract.py` → `scripts/prepare_runtime.py`
- `docker build --platform linux/arm64 ...` → `scripts/check_runtime.py` → ECR push with a NEW tag → read the image digest
- `scripts/build_web.py` → S3 upload → read the `VersionId`
- `read -rs APP_ACCESS_TOKEN` is typed by the user, never by Claude; then `scripts/deployment_parameters.py`
- `aws cloudformation deploy` for `bma-seoul-inventory` (never `--disable-rollback` for Web Revision updates)

## Step 3: Verify

After deployment:
- `aws cloudformation describe-stacks --region us-east-1 --stack-name bma-seoul-inventory` → `UPDATE_COMPLETE`
- `GET <WebUrl>/health` → `{"status":"ok"}`; unauthenticated `/api/context` → 401
- With user approval (live model + AWS calls): `.venv/bin/python scripts/verify_deployed.py`
- Report deployment result

## Step 4: Summary

Display:
- What was deployed (image tag + digest, ZIP key + VersionId) and stack status
- Verification results and any skipped checks
- Remind to update `docs/aws-deployment.md` with the verified values

## Error Recovery

### If pre-deploy checks fail (Step 1)
Stop and report. Do not stash, reset, or switch branches without the user's approval.

### If deployment fails (Step 2/3)
- `aws cloudformation describe-stack-events --region us-east-1 --stack-name bma-seoul-inventory --max-items 20`
- Web Function logs: CloudWatch log group from the `WebLogs` resource
- CloudFormation rolls back automatically; confirm the previous Web Revision is serving 100% traffic

### If a bad deployment was published — rollback
Redeploy the previous known-good parameters (prior image digest, prior ZIP `VersionId`) with the same
`aws cloudformation deploy` command. See the Rollback section of the runbook.

### If health check fails after deployment (Step 3)
- Check Web Function and Runtime logs for startup errors
- Verify environment variables in the stack parameters
- If unrecoverable, trigger the rollback procedure above
