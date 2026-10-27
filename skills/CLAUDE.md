# skills Module

## Role
BMA Skills copied to `/opt/bma/skills` (the BMA `capability_directories`). They describe procedures only;
the real read-only boundary is the tool registry, input validation and IAM. The Converse path receives
the same Markdown (with SHA-256) through `web/contract.json`.

## Key Files
- `aws-resource-inventory/SKILL.md` — inventory questions
- `aws-service-health/SKILL.md` — health and metrics checks
- `aws-operations-report/SKILL.md` — operations report structure
- `aws-security-posture/SKILL.md` — configuration and security checks (meets / needs review / unverified)

## Rules
- One directory per Skill with exactly one `SKILL.md`; `scripts/check_runtime.py` asserts there are 4.
- This `CLAUDE.md` is excluded from the image by `.dockerignore`; do not add other non-Skill files here.
- After editing a Skill, re-run `.venv/bin/python scripts/export_web_contract.py` (hash changes) and rebuild the Runtime image.
- Skills must not instruct the model to call tools that do not exist in `aws_inventory/schema.py`.
