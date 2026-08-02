# PRD: Documentation Update

> **Status (audited 2026-08-02): Implemented.**
> **Portfolio:** [PRD index](../README.md)

## Overview

The repository documentation now provides a discoverable product overview,
environment-variable contract, contribution workflow, project-specific frontend
guide, and production deployment runbook. Checked-in links and templates are
maintained as part of repository verification.

## Shipped documentation contract

| Surface | Shipped responsibility |
| --- | --- |
| `README.md` | Concise product overview, architecture, supported quick starts, key configuration, developer commands, and links to detailed guides |
| `docs/ENV_VARIABLES.md` | Runtime topology and environment-variable reference, including PostgreSQL, object storage, gRPC roles, resource limits, auth, providers, and frontend development |
| `docs/DEPLOYMENT.md` | Docker Compose and source deployment, reverse proxies, TLS, health probes, backup/restore, upgrades, and secret rotation |
| `CONTRIBUTING.md` | Repository setup, workflow, code standards, testing, verification, issue, and pull-request expectations |
| `packages/frontend/README.md` | Frontend-specific setup, structure, styling, generation, build, and test guidance |
| `.github/` templates | Bug report, feature request, and pull-request checklists |
| `AGENTS.md` and `STYLE_GUIDE.md` | Authoritative agent workflow and implementation style |
| `docs/prd/README.md` | Status-oriented product and architecture record index |

FastAPI `/docs` remains the generated API reference. Product and architecture
records remain organized in `docs/prd/implemented`, `docs/prd/active`, and
`docs/prd/backlog` according to audited delivery status.

## Deployment decision

The supported production architecture has five logical services:

```text
PostgreSQL + S3-compatible object storage + API + Scheduler + Worker
```

Docker Compose is recommended and includes RustFS as the S3-compatible store.
Source deployment runs the same three fixed application roles against separately
managed PostgreSQL and object storage. `just prod` builds protocol/frontend
artifacts, loads `config/env/prod.env`, runs all three roles in the foreground,
and shuts down the group when any role exits.

The binary-release requirement in the original proposal was retired. v0.2-era
standalone binaries predate the distributed runtime and are not supported. This
record intentionally documents that decision instead of restoring a legacy
single-process packaging path.

## Goals and outcomes

| Goal | Outcome |
| --- | --- |
| Complete README | Shipped; all detailed topics link to checked-in documents |
| Environment reference | Shipped, including the current fixed-role and object-store contract |
| Contribution guidance | Shipped with the mandatory verification workflow |
| Deployment guide | Shipped for Docker Compose and source deployment; unsupported binaries are explicitly identified |
| Frontend-specific guide | Shipped in the frontend package |

## Non-goals

- A hosted documentation site or translations.
- Hand-maintained API reference that duplicates FastAPI OpenAPI output.
- Restoring standalone binary packaging or preserving the legacy runtime.
- Treating S3 as a drop-in replacement for the local `DATA_DIR`; that broader
  storage design remains tracked separately.

## Acceptance criteria

- [x] README has no dead checked-in documentation links.
- [x] Environment variables and deployment topologies are documented.
- [x] Contribution and frontend package workflows are project-specific.
- [x] Deployment covers Docker Compose and source production paths.
- [x] The supported PostgreSQL, object-store, API, scheduler, and worker topology is consistent across guides and env templates.
- [x] `just prod` builds artifacts and supervises all fixed application roles.
- [x] Reverse proxy, TLS, health, backup/restore, update, and secret-rotation responsibilities are documented.
- [x] Legacy standalone binaries are explicitly unsupported.
- [x] GitHub issue and pull-request templates exist.
- [x] Markdown links and whitespace validation pass.

## Verification evidence

- Documentation and env contracts were audited against `Justfile`, the Compose
  stack, runtime settings, fixed-role entrypoints, and health routes on
  2026-08-02.
- On the final revision, `just verify`, `just test`, and five consecutive
  zero-retry `just test-e2e` runs passed; each e2e run completed all 351 tests.
