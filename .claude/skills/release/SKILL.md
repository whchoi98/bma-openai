---
name: release
description: Cut a semver release of this repo - bump pyproject.toml and web/package.json together, update the bilingual CHANGELOG.md, and tag. Use when asked to release, bump the version, or prepare release notes.
---

# Release Skill

Automate the release process with validation checks.

## Procedure

### 1. Pre-release Checks
- Verify working tree is clean: `git status`
- Verify all tests pass: `.venv/bin/python -m pytest`, `npm test --prefix web`, `.venv/bin/ruff check .`, `bash tests/run-all.sh`
- Check for uncommitted changes

### 2. Determine Version
- Review changes since last tag: `git log $(git describe --tags --abbrev=0 2>/dev/null || git rev-list --max-parents=0 HEAD)..HEAD --oneline`
- Apply semver rules:
  - MAJOR: Breaking API changes (HTTP routes, result envelope, tool names)
  - MINOR: New features, backward compatible (new tools, Skills, procedures)
  - PATCH: Bug fixes only

### 3. Update Changelog
- Move `## [Unreleased]` items into `## [X.Y.Z] - YYYY-MM-DD` in BOTH the English and Korean sections of `CHANGELOG.md`
- Keep category headings in English; English entries imperative, Korean entries 명사형 종결
- Update the reference links at the bottom of both sections

### 4. Create Release
- Update the version in `pyproject.toml` and `web/package.json` (keep them equal); run `npm install --package-lock-only --ignore-scripts --prefix web` to sync the lockfile version
- Use the same version for the Runtime image tag (`bma-seoul-runtime:X.Y.Z`) and web ZIP key (`web/X.Y.Z.zip`); ECR tags are immutable
- Create git tag: `git tag -a vX.Y.Z -m "Release vX.Y.Z"`
- Generate release notes from the CHANGELOG section

### 5. Summary
- Display version bump
- List key changes
- Show next steps (push tag, then deploy with `docs/runbooks/deploy-production.md`)
