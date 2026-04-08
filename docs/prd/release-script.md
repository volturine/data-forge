# PRD: Release Script All-in-One
 
## Overview
 
Create a single release script that automates the entire release process — version bumping, changelog generation, git tagging, Docker image building/publishing, binary building, and GitHub Release creation — so that cutting a release is a single command.
 
## Problem Statement
 
The current release process involves multiple manual steps spread across different tools:
 
- Version is hardcoded in `.env.example` (`APP_VERSION`) and potentially other places.
- GitHub Actions builds binaries on tag push (`.github/workflows/build.yml`).
- Docker images must be built manually (no automated publishing).
- No changelog generation — release notes are written by hand.
- No pre-release validation (tests might not pass on the release commit).
- Easy to forget a step or release with inconsistent versions.
 
### Current State
 
| Step | Automated? |
|------|-----------|
| Version bump | ❌ Manual edit of files |
| Changelog generation | ❌ Manual |
| Run tests before release | ❌ Manual |
| Git tag creation | ❌ Manual `git tag v1.x.x` |
| Binary builds | ✅ GitHub Actions on tag push |
| Docker image publish | ❌ Not automated |
| GitHub Release creation | ✅ GitHub Actions on tag push |
| Release notes | ❌ Manual |
 
## Goals
 
| # | Goal | Success Metric |
|---|------|----------------|
| G-1 | Single-command release | `just release <version>` does everything |
| G-2 | Pre-release validation | Tests and checks must pass before any release artifacts are created |
| G-3 | Automated changelog | Changelog generated from conventional commits or PR titles |
| G-4 | Version consistency | All version references updated atomically |
| G-5 | Dry-run mode | Preview what would happen without making changes |
 
## Non-Goals
 
- Automated deployment to production (release creates artifacts; deployment is separate)
- Release approval workflow (out of scope for the script)
- Hotfix branching strategy (standard git flow is sufficient)
- NPM/PyPI publishing (Data-Forge is not a library)
 
## User Stories
 
### US-1: Cut a Release
 
> As a maintainer, I want to run one command to release a new version.
 
**Acceptance Criteria:**
 
1. `just release 1.2.0` executes the full release pipeline.
2. The script:
   a. Validates the version format (semver).
   b. Checks that the working tree is clean.
   c. Checks that the current branch is `master`.
   d. Runs `just verify` and `just test` — aborts if either fails.
   e. Updates version in all relevant files.
   f. Generates changelog entries since the last release.
   g. Creates a release commit: `"release: v1.2.0"`.
   h. Creates an annotated git tag: `v1.2.0`.
   i. Pushes the commit and tag to origin.
3. GitHub Actions picks up the tag and builds binaries + Docker images.
 
### US-2: Preview a Release (Dry Run)
 
> As a maintainer, I want to preview what a release would do before executing it.
 
**Acceptance Criteria:**
 
1. `just release 1.2.0 --dry-run` shows:
   - Files that would be modified with diffs.
   - Generated changelog preview.
   - Git commands that would be executed.
2. No files are modified, no commits created, no tags pushed.
 
### US-3: Generate Changelog
 
> As a maintainer, I want an automatically generated changelog from git history.
 
**Acceptance Criteria:**
 
1. Changelog entries grouped by category:
   - **Features** — commits with `feat:` prefix or "feature" label.
   - **Fixes** — commits with `fix:` prefix or "bug" label.
   - **Breaking Changes** — commits with `BREAKING CHANGE` footer.
   - **Other** — everything else.
2. Each entry shows: short description, PR number (if available), author.
3. Changelog appended to `CHANGELOG.md` (created if it doesn't exist).
4. Unreleased changes section maintained between releases.
 
### US-4: Bump Version Across Files
 
> As a maintainer, I want all version references updated in one step.
 
**Acceptance Criteria:**
 
1. Version updated in:
   - `backend/.env.example` → `APP_VERSION`
   - `backend/core/config.py` → `app_version` default (if hardcoded)
   - `package.json` / `pyproject.toml` → `version` field (if present)
   - Any other files containing the version string
2. Script discovers version locations dynamically (grep for current version → update).
 
## Technical Design
 
### Script: `scripts/release.sh`
 
Bash script invoked via Justfile:
 
```bash
#!/usr/bin/env bash
set -euo pipefail
 
VERSION="${1:?Usage: release.sh <version> [--dry-run]}"
DRY_RUN="${2:-}"
CURRENT_VERSION=$(grep -oP 'APP_VERSION="\K[^"]+' backend/.env.example)
 
# Validations
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "Invalid semver: $VERSION"
[[ -z "$(git status --porcelain)" ]] || die "Working tree not clean"
[[ "$(git branch --show-current)" == "master" ]] || die "Not on master branch"
 
# Pre-release checks
just verify || die "Verification failed"
just test || die "Tests failed"
 
# Version bump
bump_version "$CURRENT_VERSION" "$VERSION"
 
# Changelog
generate_changelog "$CURRENT_VERSION" "$VERSION" >> CHANGELOG.md
 
# Commit, tag, push
git add -A
git commit -m "release: v${VERSION}"
git tag -a "v${VERSION}" -m "Release v${VERSION}"
git push origin master --follow-tags
```
 
### Justfile Commands
 
```just
release version *args:
    bash scripts/release.sh {{version}} {{args}}
 
release-dry-run version:
    bash scripts/release.sh {{version}} --dry-run
```
 
### Changelog Generation
 
Use git log between tags:
 
```bash
generate_changelog() {
    local from="v$1" to="HEAD"
    echo "## v$2 ($(date +%Y-%m-%d))"
    echo ""
    echo "### Features"
    git log "$from..$to" --oneline --grep="^feat" --format="- %s (%h)"
    echo ""
    echo "### Fixes"
    git log "$from..$to" --oneline --grep="^fix" --format="- %s (%h)"
    echo ""
    echo "### Other"
    git log "$from..$to" --oneline --invert-grep --grep="^feat\|^fix" --format="- %s (%h)"
}
```
 
### GitHub Actions Integration
 
Update `.github/workflows/build.yml` to also:
- Build and push Docker images on tag push (see Docker Release PRD).
- Attach `CHANGELOG.md` excerpt to the GitHub Release body.
 
### Version File Discovery
 
The script finds all files containing the current version:
 
```bash
bump_version() {
    local old="$1" new="$2"
    grep -rl "$old" --include="*.py" --include="*.toml" --include="*.json" --include="*.env*" . | while read -r file; do
        sed -i "s/$old/$new/g" "$file"
    done
}
```
 
## File Deliverables
 
| File | Purpose |
|------|---------|
| `scripts/release.sh` | Main release script |
| `CHANGELOG.md` | Changelog (created on first release) |
| Updated `Justfile` | `release` and `release-dry-run` commands |
| Updated `.github/workflows/build.yml` | Docker publish on tag, changelog in release notes |
 
## Risks
 
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Version grep matches unintended strings | Low | Medium | Use precise patterns with file path context |
| Push fails after local commit/tag | Low | High | Script checks remote connectivity before committing |
| Changelog formatting inconsistent | Medium | Low | Template-based generation; review in dry-run |
 
## Acceptance Criteria
 
- [ ] `just release 1.0.0 --dry-run` shows preview without side effects
- [ ] `just release 1.0.0` bumps version, generates changelog, commits, tags, and pushes
- [ ] Tests and verification run before any release artifacts are created
- [ ] Version updated in all relevant files consistently
- [ ] `CHANGELOG.md` has properly categorized entries
- [ ] GitHub Actions builds trigger on the pushed tag
- [ ] Release can be run from a clean `master` checkout
 