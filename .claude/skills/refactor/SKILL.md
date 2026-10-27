---
name: refactor
description: Refactor code in this repo without changing behavior, verifying with pytest and node:test after each step. Use when asked to restructure, deduplicate, or simplify Python in aws_inventory/ or webapp/, or JavaScript in web/.
---

# Refactor Skill

Refactor existing code to improve quality without changing behavior.

## Principles
- Improve structure without changing behavior
- Single Responsibility Principle (SRP)
- Remove duplicate code (DRY)
- Small, incremental steps with verification

## Process

### 1. Analysis
- Identify the target code and its tests (`tests/test_*.py`, `web/tests/*.test.js`)
- Map all callers and dependencies, including cross-language contracts:
  Python `TOOL_SCHEMAS` / `webapp/evidence.py` / `webapp/bma.py INSTRUCTIONS` feed `web/contract.json`
- Confirm test coverage exists (suggest adding tests first if not)

### 2. Plan
Present the refactoring plan to the user:
- What will change
- What will NOT change (behavior preservation, result envelope fields, HTTP error codes)
- Risk assessment (low/medium/high)

### 3. Execute
- Make changes in small, verifiable steps
- Run tests after each step: `.venv/bin/python -m pytest`, `npm test --prefix web`, `.venv/bin/ruff check .`
- If Python contracts moved, run `.venv/bin/python scripts/export_web_contract.py` and confirm `git diff web/contract.json` is empty
- Keep commits atomic

### 4. Verify
- Confirm all existing tests pass
- Verify no behavior changes (sample mode: `DATA_MODE=sample node web/index.js`)
- Check that the refactoring achieved its goal
- Never refactor `runtime/lifecycle/server.py` (upstream file)
