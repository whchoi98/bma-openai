# scripts Module

## Role
Operational Python scripts for preflight, build, deployment and verification, plus the Claude harness
shell scripts (`setup.sh`, `install-hooks.sh`). Evidence is written to `artifacts/` (gitignored).

## Key Files
| Group | Scripts | AWS access |
|---|---|---|
| Build (local) | `export_web_contract.py`, `build_web.py`, `prepare_runtime.py`, `check_runtime.py`, `check_browser.py`, `check_markdown_browser.py` | none |
| Preflight | `preflight.py` (`--list-models`), `check_network.py` | read-only STS / model list |
| Deploy | `deployment_parameters.py`, `deploy_east_region.py`, `deploy_investigations.py` | writes stacks |
| Live verify | `live_smoke.py`, `verify_deployed.py`, `verify_deployed_browser.py`, `verify_extended_deployed.py`, `verify_extended_browser.py`, `verify_investigations.py`, `verify_investigations_browser.py` | bounded live queries + model calls |
| Retire | `retire_oregon_deployment.py` | deletes recorded Oregon resources |
| Harness | `setup.sh`, `install-hooks.sh` | none |

## Rules
- Ask the user before running any Deploy, Live verify or Retire script: they use the real account and incur cost.
- Scripts that need the account read `artifacts/deployment-context.json` and stop if STS returns a different account; never overwrite the pinned expected account.
- Keep live checks bounded (max 2 resources per service, 15-minute metric windows) as in `live_smoke.py`.
- Never print `APP_ACCESS_TOKEN` or the contents of `artifacts/deployment-secrets.json`.
