# AGENTS.md

**Mandatory for all AI assistants.** Read fully before any work in this repository.

## Commands

```bash
just verify          # format + static checks only
just format          # ruff format + prettier
just test            # backend pytest + frontend unit tests
just test-e2e        # e2e tests with Playwright
just check           # ruff + mypy + svelte-check + eslint
just dev             # start API, worker, scheduler, and frontend
```

- E2E must be run only via `just test-e2e`. Do not run Playwright e2e commands directly.

## Package Managers

- **svelte**: `bun` — use `bun add` to install packages, never edit `package.json` directly
- **python**: `uv` — use `uv add` to install packages, never edit `pyproject.toml` directly

## Definition of Done

- For code or config changes, run `just verify`, `just test`, and `just test-e2e` before declaring any task done or asking for review
- For markdown-only changes, these commands are not required unless the user explicitly asks for them
- If `just verify` fails, fix the underlying issues immediately
- If `just test` or `just test-e2e` fails for a code/config change, fix the underlying issues immediately
- Do not ignore or suppress warnings, even if they seem unrelated
- Write backend Python tests for new/changed functionality
- Pre-existing warnings are tech debt — fix them, do not ignore them
- If a warning cannot be fixed (third-party stubs), suppress with an inline comment explaining why

## Workflow

1. **Explore** — Read relevant files, understand context
2. **Plan** — Produce a structured plan before coding
3. **Code** — Implement. Use parallel agents when possible
4. **Verify** — Run the required validation commands for the change type before declaring any task done
5. **Reviewer** — Ask for review and address feedback
6. **Finish** — Clean up, ensure tests pass

## Principles

1. Don't assume. Don't hide confusion. Surface tradeoffs.
2. Minimum code that solves the problem. Nothing speculative.
3. Touch only what you must. Clean up only your own mess.
4. Define success criteria. Loop until verified.

## Non-Negotiables

- **No workarounds.** Fix root causes instead of patching symptoms
- **No hidden compromises.** Dont hide or ignore tradeoffs
- **No silent behavior changes.** All changes explicit and intentional
- **Redesign over hotfix.** If existing code is wrong, redesign properly
- **Fix warnings, not just errors.** Treat warnings as bugs
- **Autonomous completion.** Continue until every requirement is implemented, tested, and verified
- **No legacy support.** New features/redesigns must not preserve legacy paths or backward compatibility
- **No fallback logic.** Do not add permissive fallback/defaulting behavior unless explicitly asked for.

## Code Style

See [`STYLE_GUIDE.md`](STYLE_GUIDE.md)

## Git

- NEVER push to remote unless explicitly asked
- Local commits only
- Create PRs for sharing changes

