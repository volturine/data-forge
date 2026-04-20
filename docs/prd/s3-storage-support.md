# PRD: S3 Storage Support

## Overview

Enable Data-Forge to use an S3-compatible path as its `DATA_DIR`, storing all namespaces, uploads, cleaned data, exports, and logs in S3 instead of the local filesystem. When `DATA_DIR` points to S3, PostgreSQL becomes the mandatory metadata backend; local `DATA_DIR` continues to support both SQLite and PostgreSQL.

## Problem Statement

Data-Forge stores all persistent state — uploaded files, Iceberg tables, exports, and per-namespace SQLite databases — on the local filesystem under `DATA_DIR`. This creates several limitations:

- **No horizontal scaling**: Multiple app instances cannot share a single local `DATA_DIR`.
- **Storage capacity bound to disk**: Large datasets are limited by local disk size.
- **No durability guarantees**: Local disk failures risk data loss without manual backup.
- **No cloud-native deployment**: Users deploying on Kubernetes, ECS, or similar platforms cannot use ephemeral containers without external volume mounts.

### Current State

| Concern | Status |
|---------|--------|
| Local file storage | ✅ `DATA_DIR` on local filesystem |
| Namespace isolation | ✅ `data_dir/namespaces/{ns}/` per namespace |
| SQLite metadata | ✅ `namespace.db` per namespace, `app.db` shared |
| PostgreSQL metadata | ❌ Not supported for app/namespace databases |
| S3 file storage | ❌ Not supported |
| Multi-instance deployment | ❌ Requires shared volume mount |

### Target State

| Concern | Status |
|---------|--------|
| Local file storage | ✅ Unchanged |
| S3 file storage | ✅ `s3://bucket/prefix` as `DATA_DIR` |
| SQLite metadata (local DATA_DIR) | ✅ Unchanged |
| PostgreSQL metadata (local DATA_DIR) | ✅ Optional |
| PostgreSQL metadata (S3 DATA_DIR) | ✅ **Required** |
| Multi-instance deployment | ✅ Via S3 + PostgreSQL |

## Goals

| # | Goal | Success Metric |
|---|------|----------------|
| G-1 | S3 as primary storage backend | All file I/O (uploads, clean, exports, logs) works against S3 when `DATA_DIR` is an S3 URI |
| G-2 | Enforce PostgreSQL when using S3 | Startup fails with a clear error if `DATA_DIR` is S3 and `DATABASE_URL` is SQLite |
| G-3 | Transparent abstraction | Application code uses a storage interface; callers don't know if the backend is local or S3 |
| G-4 | S3-compatible providers | Works with AWS S3, MinIO, Cloudflare R2, Backblaze B2 via endpoint override |
| G-5 | Iceberg integration with S3 | Iceberg tables can be read/written with S3 paths using PyIceberg's S3 FileIO |

## Non-Goals

- GCS or Azure Blob support (future — the abstraction should allow it but only S3 is implemented)
- Streaming uploads directly to S3 from the browser (files are still uploaded to the backend first)
- S3 event notifications for automated ingestion (see Monitored Datasource Folder PRD)
- Migrating existing local data to S3 (manual migration guide is sufficient)

## User Stories

### US-1: Configure S3 as Data Directory

> As a user, I want to set `DATA_DIR=s3://my-bucket/data-forge` so all platform data is stored in S3.

**Acceptance Criteria:**

1. `DATA_DIR` accepts `s3://bucket/prefix` format.
2. Additional env vars are available: `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_REGION`.
3. If `S3_ACCESS_KEY_ID`/`S3_SECRET_ACCESS_KEY` are omitted, the SDK falls back to default credential chain (IAM roles, instance profiles, `~/.aws/credentials`).
4. On startup, the app validates S3 connectivity by listing the bucket prefix.
5. If `DATA_DIR` starts with `s3://` and `DATABASE_URL` starts with `sqlite`, startup fails with: `"S3 storage requires PostgreSQL. Set DATABASE_URL to a PostgreSQL connection string."`

### US-2: Upload Files to S3-Backed Instance

> As a user, I want to upload CSV/Parquet files and have them stored in S3 transparently.

**Acceptance Criteria:**

1. Chunked upload flow works identically to local — backend receives chunks, assembles the file.
2. Assembled file is written to `s3://bucket/prefix/namespaces/{ns}/uploads/{filename}`.
3. Datasource `config.file_path` stores the S3 URI.
4. Download/preview of uploaded files reads from S3.

### US-3: Build Outputs Written to S3

> As a user, I want analysis builds to write Iceberg tables to S3.

**Acceptance Criteria:**

1. Iceberg table location is `s3://bucket/prefix/namespaces/{ns}/clean/{datasource_id}/{branch}/`.
2. PyIceberg uses S3FileIO with configured credentials.
3. Iceberg catalog remains SQLite-on-S3 **or** switches to a PostgreSQL-backed catalog (decision: prefer PostgreSQL catalog when `DATABASE_URL` is PostgreSQL).
4. Snapshot operations (list, rollback, delete) work against S3-backed Iceberg tables.

### US-4: Export and Log Files on S3

> As a user, I want exports and log files to be stored in S3.

**Acceptance Criteria:**

1. Export files written to `s3://bucket/prefix/namespaces/{ns}/exports/`.
2. Iceberg log tables written to `s3://bucket/prefix/logs/iceberg/`.
3. Export download endpoint streams from S3.

## Technical Design

### Storage Abstraction Layer

Introduce a `StorageBackend` protocol with two implementations:

```python
class StorageBackend(Protocol):
    async def read(self, path: str) -> bytes: ...
    async def read_stream(self, path: str) -> AsyncIterator[bytes]: ...
    async def write(self, path: str, data: bytes | BinaryIO) -> None: ...
    async def write_stream(self, path: str, chunks: AsyncIterator[bytes]) -> None: ...
    async def delete(self, path: str) -> None: ...
    async def exists(self, path: str) -> bool: ...
    async def list_dir(self, prefix: str) -> list[str]: ...
    async def get_url(self, path: str) -> str: ...  # presigned URL for S3, file:// for local
```

- `LocalStorageBackend`: Current filesystem operations wrapped in the protocol.
- `S3StorageBackend`: Uses `aiobotocore` / `s3fs` for async S3 operations.

The backend is selected at startup based on `DATA_DIR` prefix and exposed as a singleton dependency.

### Namespace Path Resolution

`NamespacePaths` currently returns `pathlib.Path` objects. With S3:

- Paths become string URIs (`s3://...` or `/local/...`).
- `NamespacePaths` returns `str` and the storage backend resolves the I/O.
- Polars `scan_parquet` / `read_parquet` natively supports `s3://` URIs when `storage_options` are provided.

### Configuration

New environment variables:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `S3_ENDPOINT_URL` | No | AWS default | Custom endpoint for MinIO/R2/B2 |
| `S3_ACCESS_KEY_ID` | No | SDK chain | AWS access key |
| `S3_SECRET_ACCESS_KEY` | No | SDK chain | AWS secret key |
| `S3_REGION` | No | `us-east-1` | AWS region |
| `S3_STORAGE_OPTIONS` | No | `{}` | JSON dict of extra `storage_options` for Polars/PyIceberg |

### Validation Matrix

| DATA_DIR | DATABASE_URL | Valid? |
|----------|-------------|--------|
| Local path | `sqlite:///...` | ✅ |
| Local path | `postgresql+psycopg://...` | ✅ |
| `s3://...` | `sqlite:///...` | ❌ Startup error |
| `s3://...` | `postgresql+psycopg://...` | ✅ |

### Iceberg on S3

- PyIceberg's `SqlCatalog` can use PostgreSQL as the catalog backend when `DATABASE_URL` is PostgreSQL.
- Table warehouse location set to `s3://bucket/prefix/namespaces/{ns}/clean/`.
- `storage_options` passed from config for authentication.

### Migration Path

- No automated migration from local to S3.
- Provide a CLI command or documentation for manual migration: `data-forge migrate-storage --from /local/data --to s3://bucket/prefix`.

## Dependencies

| Dependency | Purpose |
|-----------|---------|
| `aiobotocore` or `s3fs` | Async S3 I/O |
| `boto3` (transitive) | S3 SDK |
| PostgreSQL support (see PostgreSQL PRD) | Required metadata backend for S3 mode |

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Latency increase for file operations | High | Medium | Use streaming I/O, presigned URLs for downloads, local temp cache for processing |
| S3 eventual consistency edge cases | Low | Medium | Use strong-read-after-write (default since Dec 2020 for AWS S3) |
| Credential management complexity | Medium | Medium | Support IAM roles, document credential chain |
| Large file upload memory pressure | Medium | High | Stream chunks to S3 without buffering entire file |

## Acceptance Criteria

- [ ] `DATA_DIR=s3://test-bucket/df` with PostgreSQL `DATABASE_URL` → app starts, uploads, builds, and exports work
- [ ] `DATA_DIR=s3://test-bucket/df` with SQLite `DATABASE_URL` → app fails with clear error
- [ ] Local `DATA_DIR` with SQLite → unchanged behavior (no regression)
- [ ] Local `DATA_DIR` with PostgreSQL → works correctly
- [ ] MinIO endpoint override works for local S3-compatible testing
- [ ] Iceberg snapshots readable from S3
- [ ] E2e test covering upload → build → export on S3 backend (MinIO in CI)