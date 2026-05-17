# PRD: PostgreSQL Backend Support

## Status

Implemented and superseded.

Data-Forge now runs on a Postgres-only metadata/runtime architecture. This document previously described a transitional dual-backend plan; that design is no longer relevant because the repository now supports only PostgreSQL runtime metadata paths.

## Final state

- `DATABASE_URL` is required and must point to PostgreSQL
- shared/runtime-global tables live in `public`
- tenant-scoped tables live in namespace schemas
- runtime IPC, logging, and build metadata are Postgres-backed
- Docker, dev, tests, and e2e all target PostgreSQL

## Follow-up guidance

When updating docs or architecture, describe PostgreSQL as the single supported metadata backend.
