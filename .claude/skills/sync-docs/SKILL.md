---
name: sync-docs
description: Synchronize this repo's documentation (root and module CLAUDE.md, docs/architecture.md, docs/reference/, runbooks, README) with the current code and score CLAUDE.md quality. Use after significant code changes or when asked to update or audit docs.
---

# Sync Docs Skill

Synchronize project documentation with current code state.

## Actions

### 1. Quality Assessment
Score each CLAUDE.md file (0-100) across:
- Commands/workflows (20 pts)
- Architecture clarity (20 pts)
- Non-obvious patterns (15 pts)
- Conciseness (15 pts)
- Currency (15 pts)
- Actionability (15 pts)

Apply anti-pattern deductions:
- Over 500 lines (-15)
- Vague instructions (-10)
- Duplicated docs (-10)
- No test guidance (-10)
- Contains secrets (-20)

Output quality report with grades (A-F) before making changes.

### 2. Root CLAUDE.md Sync
- Update Overview, Tech Stack, Conventions, Key Commands
- Verify commands are copy-paste ready against `pyproject.toml`, `web/package.json` and `scripts/`
- Keep counts current (MCP tools in `aws_inventory/schema.py`, Skills in `skills/*/SKILL.md`)

### 3. Architecture Doc Sync
- Update `docs/architecture.md` (English and Korean sections identically) to reflect current structure
- Reflect resources in `infra/bootstrap.yaml` and `infra/template.yaml`

### 4. Module CLAUDE.md Audit
- Source roots: `aws_inventory/ webapp/ web/ runtime/ infra/ scripts/ skills/ tests/`
- Create CLAUDE.md for modules missing one (never under `webapp/static/`)
- Update existing module CLAUDE.md files if out of date
- Score each module CLAUDE.md

### 5. Reference, ADR and Runbook Audit
- Check every Code Pointer path in `docs/reference/*.md` exists; refresh `docs/reference/INDEX.md` and the root `<!-- AUTO-MANAGED:references -->` block
- Check recent commits for undocumented architectural decisions
- Verify `docs/runbooks/deploy-production.md` matches the README deployment commands
- Flag stale ADRs and outdated runbooks

### 6. README.md Sync
- Update the project structure section in both language sections to match the actual layout

### 7. Report
Output before/after quality scores, anti-patterns detected, and list of all changes.
