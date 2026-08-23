# Data-Forge

Local-first no-code data analysis: visual Polars pipelines, Iceberg storage, scheduled builds.

**Stack:** Python 3.14 + FastAPI + uv · SvelteKit 5 (runes) + Bun · Panda CSS · PostgreSQL · Iceberg · protobuf (`packages/protocol`)

## Commands

```bash
just install              # deps + protocol generation
just dev                  # API, worker, scheduler, frontend
just format               # ruff + prettier
just check                # lint/types/protocol
just verify               # format + static checks
just test                 # backend pytest + frontend unit
just test-e2e             # Playwright only via this recipe
just generate-protocol
```

- Frontend: `bun add` / `bun remove` — never hand-edit `package.json`.
- Python: `uv add` / `uv remove` in the package dir — never hand-edit `pyproject.toml`.
- Prefer `just` recipes over ad-hoc scripts.

## Packages

`packages/{backend,worker,scheduler,frontend,protocol}` — no shared Python package.

- Import boundaries: `scripts/check_package_boundaries.py` (e.g. worker ↛ `backend_core`/`modules`).
- Protocol: edit protos → `just generate-protocol` → commit generated code. Never hand-edit `dataforge_protocol` or `frontend/src/lib/protocol`.
- Env: `docker/env/` — see `docs/ENV_VARIABLES.md`.

## Definition of done

Code/config: `just verify` && `just test` && `just test-e2e` before done or review. Markdown-only: skip unless asked.

- Fix failures and warnings immediately (pre-existing ones when you touch the area). Unfixable third-party stub warnings: inline comment why.
- Add backend tests for new/changed backend behavior.

## Docs

| Doc | Use for |
|-----|---------|
| [`STYLE_GUIDE.md`](STYLE_GUIDE.md) | Code style |
| [`README.md`](README.md) | Overview, architecture |
| [`docs/prd/`](docs/prd/) | Product/architecture by status: `implemented/`, `active/`, `backlog/` |
| [`docs/prd/README.md`](docs/prd/README.md) | PRD index — update on add/move/material change |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | PR process |
| [`docs/ENV_VARIABLES.md`](docs/ENV_VARIABLES.md) · [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Env, deploy |

PRDs go by delivery status, not topic.

## Principles

- Do not preserve backward compatibility. Remove obsolete paths instead of adding compatibility layers, fallbacks, or migrations.
- Choose the simplest implementation that fully meets the current requirements. Avoid speculative abstractions, configuration, and indirection.
- Grow the system in layers. Start from the smallest version that works end to end, and add each new capability on top of a product that already works. Never trade a working product for unfinished complexity.
- Keep components modular and concerns clearly separated.
- Prefer established, well-maintained libraries when they reduce overall complexity or improve reliability. Do not reimplement common functionality without a clear reason.
- Lean on the dependencies already in the project before writing your own implementation or adding packages. Do not assume a library lacks a capability without checking its documentation and types.
- Make architectural decisions for the long term. Do not accept a stopgap that only works for now and is meant to be replaced later.

## Problem solving

- Start from the intended outcome, then trace the behavior across every relevant layer before changing code.
- Form a causal explanation and actively look for evidence that disproves it.
- Fix the cause where the responsibility belongs. Prefer clear ownership and isolation boundaries over patches at the point where symptoms appear.
- When one fix reveals another failure, investigate it independently instead of forcing it into the previous explanation.
- Before finishing, be able to explain the root cause, why the symptoms were misleading, what now prevents recurrence, and what evidence proves the fix.
