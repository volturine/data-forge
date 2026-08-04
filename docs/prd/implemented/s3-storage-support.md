# PRD: S3 Storage Support

> **Status (completed 2026-08-04): Implemented.**
> **Portfolio:** [PRD index](../README.md)

## Overview

Product data lives in an S3-compatible object store. PostgreSQL remains the
metadata backend. Local `DATA_DIR` is process scratch only.

## Design

### Namespace is the bucket

That is the entire mapping:

| Namespace   | Bucket      |
|-------------|-------------|
| `default`   | `default`   |
| `analytics` | `analytics` |

No base name, no suffix, no rewriting. Underscores are allowed (e.g. `team_a`).
Invalid names are rejected.

### Keys

```text
s3://{namespace}/uploads/...
s3://{namespace}/clean/...
s3://{namespace}/exports/...
s3://{namespace}/runtime-artifacts/...
```

### Namespace creation

- `GET /api/v1/namespaces/storage-plan?name=…` previews bucket + roots
- `POST /api/v1/namespaces` registers the name and creates the bucket
- UI shows the bucket and path roots before create

### Config

| Variable | Role |
| --- | --- |
| `OBJECT_STORE_ENDPOINT` | Endpoint |
| `OBJECT_STORE_REGION` | Region |
| `OBJECT_STORE_ACCESS_KEY` / `OBJECT_STORE_SECRET_KEY` | Credentials |

There is no `OBJECT_STORE_BUCKET` or `OBJECT_STORE_PREFIX`.
