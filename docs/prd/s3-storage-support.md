# PRD: S3 Storage Support

> **Status (2026-05-28): Partially implemented.**
> **Current truth:** Object-store support exists for Iceberg/runtime paths, but full S3-backed DATA_DIR semantics described here are not the current shipped default.
> **Portfolio status index:** `docs/prd/README.md`


## Status

Draft, updated for the current Postgres-only runtime.

## Overview

Enable Data-Forge to use an S3-compatible path as `DATA_DIR` for uploads, clean data, exports, and logs while keeping PostgreSQL as the mandatory metadata backend.

## Assumptions

- Metadata/runtime state is stored in PostgreSQL only
- S3 support concerns filesystem/object storage, not metadata database selection
- Any supported S3 deployment must keep `DATABASE_URL` pointed at PostgreSQL

## Goals

- support `s3://bucket/prefix` for file storage paths
- keep namespace isolation in object storage layout
- preserve PostgreSQL-backed Iceberg/runtime metadata behavior
- fail fast if S3 configuration is invalid

## Non-goals

- reintroducing any alternate file-backed metadata mode
- split metadata backends by environment
- alternate database backends for S3 deployments
