# Data-Forge

Local-first no-code data analysis: visual Polars pipelines, Iceberg storage, scheduled builds.

**Stack:** Python 3.14 + FastAPI + uv · SvelteKit 3 + Svelte 5 (runes) + Bun · Panda CSS · PostgreSQL · Iceberg · protobuf (`packages/protocol`)

## Commands

```bash
just install      # dependencies + protocol generation
just dev          # local stack
just verify       # formatting + static checks
just test         # all unit/integration suites
just test-e2e     # browser/runtime tests + mandatory 50-tab gate
```

Run tests through public `just test*` recipes in isolated Docker Compose enclaves,
never pytest or Playwright on the host. `just test` runs suites sequentially.
Inside enclaves, loopback is valid within one container; use Compose DNS between
containers. Use the Mac's Tailscale address for published local dev/prod services.

- Frontend: `bun add` / `bun remove` — never hand-edit `package.json`.
- Python: `uv add` / `uv remove` in the package dir — never hand-edit `pyproject.toml`.

## Packages

`packages/{backend,worker,scheduler,frontend,protocol}` — no shared Python package.

- Respect `scripts/check_package_boundaries.py`: worker must not import backend `backend_core`/`modules`.
- `worker` is the Docker-owning manager; a compute worker is its isolated analysis/datasource container. Keep those names distinct.
- After editing protos, run `just generate-protocol`. Never hand-edit or commit ignored generated output (`dataforge_protocol/`, `buf/`, frontend `src/lib/protocol`).
- Environment configuration lives in `docker/env/`.

## Definition of done

For code/config, run focused checks first, then `just verify`, `just test` and
`just test-e2e` before declaring done. Markdown-only: skip these unless asked.

- Preserve required workloads, limits, deadlines and assertions; profiles do not replace the mandatory stress gate.
- Fix failures/warnings in touched areas. Explain unavoidable third-party stub warnings inline. Cover changed backend behavior with backend tests.
- Reuse checks only when their inputs are unchanged; label reused or incomplete evidence. Inspect saved exits/artifacts before rerunning work after an agent failure.
- Before expensive experiments, state the hypothesis and required signal; preflight the exact command and collector on a small case. Reassess inconclusive runs before repeating them.
- For PR work, inspect all current-head checks, including security findings. After a stacked merge, verify the destination head too; report pending/failing checks explicitly. Merge only the authorized PR/base.

## Docs

Read [engineering guidance](docs/agent-guidance.md) before design/debugging and
[runtime invariants](docs/runtime-invariants.md) before changing runtime/durable
work, locks, previews, capacity, scheduling or private storage cleanup.

- [README](README.md): architecture; [style](STYLE_GUIDE.md), [review standards](CODING_STANDARDS.md), [contributing](CONTRIBUTING.md): conventions and PR process.
- [PRDs](docs/prd/README.md): grouped by delivery status (`implemented/`, `active/`, `backlog/`); update the index on additions, moves or material changes.
- [Environment](docs/ENV_VARIABLES.md), [deployment](docs/DEPLOYMENT.md): operations.
