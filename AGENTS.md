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

Public `just test*` recipes run in isolated Docker Compose enclaves, one per
suite invocation; `just test` runs the per-suite recipes sequentially. Never
run pytest or Playwright directly on the host. Inside an enclave, loopback is
valid for process-internal tests; use Docker Compose DNS for services in other
containers. The Mac Tailscale-address rule applies only to services published
by local dev/prod stacks, not container-internal test services.

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

| Doc                                                                                           | Use for                                                               |
| --------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| [`STYLE_GUIDE.md`](STYLE_GUIDE.md)                                                            | Code style                                                            |
| [`README.md`](README.md)                                                                      | Overview, architecture                                                |
| [`docs/prd/`](docs/prd/)                                                                      | Product/architecture by status: `implemented/`, `active/`, `backlog/` |
| [`docs/prd/README.md`](docs/prd/README.md)                                                    | PRD index — update on add/move/material change                        |
| [`CONTRIBUTING.md`](CONTRIBUTING.md)                                                          | PR process                                                            |
| [`CODING_STANDARDS.md`](CODING_STANDARDS.md)                                                  | Reviewer-only judgment rules                                          |
| [`docs/agent-guidance.md`](docs/agent-guidance.md)                                            | General engineering and problem-solving guidance                      |
| [`docs/runtime-invariants.md`](docs/runtime-invariants.md)                                    | Runtime, locking, preview, and capacity constraints                   |
| [`docs/ENV_VARIABLES.md`](docs/ENV_VARIABLES.md) · [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Env, deploy                                                           |

PRDs go by delivery status, not topic.
