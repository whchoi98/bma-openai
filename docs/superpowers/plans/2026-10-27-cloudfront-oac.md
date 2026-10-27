# CloudFront OAC implementation plan

**Goal:** Put both existing Web Functions behind CloudFront for Seoul users,
preserving application authentication, SSE and private downloads.

**Architecture:** Each existing app stack owns its distribution and Lambda Web
OAC. The regional origin remains in us-east-1. Deploy the
distribution before switching the endpoint to IamAuth; attach an exact
distribution-to-endpoint resource policy through the documented Lambda Web
PutResourcePolicy API. No model, Runtime, data bucket or resource-query IAM
changes are required.

**Approval:** The user explicitly requested OAC for both Web Functions after
reviewing the proposed cache/authentication/SSE design.

**Constraints:** `sigv4`, `always-amz-auth`, origin type `lambda`;
Authorization explicitly forwarded by every behavior; viewer Host excluded;
PriceClass_All includes Seoul; private responses and errors are not cached.
Private behaviors use zero minimum/default/maximum TTL and origin no-store.
The account's custom-cache-policy quota was exhausted; existing policies did
not meet the auth boundary. Inline ForwardedValues retains exact forwarding
and cache controls without deleting unrelated policies or increasing the quota.

- [x] Check official AWS guide and actual CloudFormation/API schemas.
- [x] Add public static response cache controls and GET/HEAD tests.
- [x] Add distribution/OAC/cache behaviors and staged endpoint auth parameter to both templates.
- [x] Add a bounded account-checked deployer with change-set allow lists,
      conditional policy writes, snapshots and final verification.
- [x] Test policy boundaries and validate both templates.
- [x] Build and deploy both apps; attach scoped policies before IamAuth cutover.
- [x] Verify private-origin denial, edge cache hits, authentication isolation,
      SSE, uploads and existing downloads; obtain a Seoul vantage where available.
- [x] Update public URLs, deployment/runbook documentation and evidence.

Files: `infra/template.yaml`, `studio/infra/template.yaml`,
`scripts/deploy_cloudfront.py`, `scripts/verify_cloudfront.py`,
`tests/test_cloudfront.py`, both Web servers and their cache tests.

Final evidence: `artifacts/cloudfront/summary.json`, `final-state.json`,
`verification.json`, `browser/summary.json`, and the before/after latency files.
Both distributions are Deployed, both endpoints use IamAuth, source packages
match deployed revisions/workers, and all four role definitions per app are unchanged.
Measured from ap-northeast-2a: public HTML cache-hit median TTFB is 11.46 ms
(desk) and 10.65 ms (Studio), with ICN edge identifiers. This does not measure
model generation latency or active long-running SSE.
