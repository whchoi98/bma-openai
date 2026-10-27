# scripts Module

## Role
Operational Python scripts for preflight, build, deployment and verification, plus the Claude harness
shell scripts (`setup.sh`, `install-hooks.sh`). Evidence is written to `artifacts/` (gitignored).

## Key Files
| Group | Scripts | AWS access |
|---|---|---|
| Build (local) | `export_web_contract.py`, `build_web.py`, `prepare_runtime.py`, `check_runtime.py`, `check_browser.py`, `check_markdown_browser.py`, `capture_screenshots.py` (README images in `docs/images/`: `desk` sample mode, `studio` fixtures from `studio/scripts/`; needs `.studio-venv`) | none |
| Preflight | `preflight.py` (`--list-models`), `check_network.py` | read-only STS / model list |
| Deploy | `deployment_parameters.py`, `deploy_east_region.py`, `deploy_investigations.py` | writes stacks |
| CloudFront/OAC deploy | `deploy_cloudfront.py prepare\|cutover\|inspect --app desk\|studio\|both` | STS, code S3 uploads, scoped Change Sets, exact Web Function resource policies |
| CloudFront verify | `verify_cloudfront.py` (`--app desk\|studio` optional) | read-only configuration/existing results, one tiny Studio upload; no new model generation |
| Live verify | `live_smoke.py`, `verify_deployed.py`, `verify_deployed_browser.py`, `verify_extended_deployed.py`, `verify_extended_browser.py`, `verify_investigations.py`, `verify_investigations_browser.py` | bounded live queries + model calls |
| Live capture | `capture_live_screenshots.py` (README `*-live-*.png` from both CloudFront URLs; Desk overview only, existing Studio jobs) | GET-only browser session with the real access key; no queries, uploads or model calls |
| Retire | `retire_oregon_deployment.py` | deletes recorded Oregon resources |
| Harness | `setup.sh`, `install-hooks.sh` | none |

AI Document Studio has its own build, deploy and live-verify scripts in `studio/scripts/` (see `studio/CLAUDE.md`).

## Rules
- Ask the user before running any Deploy, Live verify or Retire script: they use the real account and incur cost.
- Scripts that need the account read `artifacts/deployment-context.json` and stop if STS returns a different account; never overwrite the pinned expected account.
- Keep live checks bounded (max 2 resources per service, 15-minute metric windows) as in `live_smoke.py`.
- Never print `APP_ACCESS_TOKEN` or the contents of `artifacts/deployment-secrets.json`.
- CloudFront rollout order is `prepare`, `cutover`, then `verify_cloudfront.py`; see `docs/runbooks/cloudfront-oac.md`. Evidence and original deployment/template/policy backups live in `artifacts/cloudfront/`.
- `deploy_cloudfront.py` preserves Runtime and model configuration, keeps current endpoint auth during prepare, then sets `IamAuth` after the exact distribution policy and authenticated edge path are verified. Post-cutover HTTP failures never reopen the origin.
- `verify_cloudfront.py` verifies direct-origin 403, preserved Bearer auth, public asset cache hits, uncached private responses, existing terminal SSE/downloads and a small UTF-8-named upload. Its current execution location is not a Seoul latency measurement or a long-running active-stream test.
- Later Web code releases need invalidation of the actual recorded distribution IDs because static asset names are not content-hashed. Do not use example IDs or invalidate unrelated distributions.
