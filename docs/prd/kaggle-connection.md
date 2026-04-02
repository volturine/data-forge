# PRD: Kaggle Connection

## Overview

Integrate Kaggle as a first-class data source in Data-Forge, enabling users to browse, search, and ingest Kaggle datasets directly into the platform as managed datasources.

## Problem Statement

Users currently import data by uploading local files (CSV, Parquet, JSON) or connecting to databases. There is no way to discover or ingest datasets from public dataset hubs. Kaggle hosts over 200,000 datasets across every domain — connecting to it removes the friction of manual download → upload workflows and opens Data-Forge to a much larger universe of input data.

## Goals

| # | Goal | Success Metric |
|---|------|----------------|
| G-1 | Browse and search Kaggle datasets from within Data-Forge | Users can find datasets without leaving the app |
| G-2 | One-click ingest of a Kaggle dataset as a managed datasource | Dataset appears in datasource list within 60 seconds of selection (network permitting) |
| G-3 | Track provenance of Kaggle-originated datasources | `source_type` and metadata clearly identify Kaggle origin |
| G-4 | Support Kaggle dataset versioning | Users can re-ingest a newer version or pin to a specific version |

## Non-Goals

- Uploading data back to Kaggle
- Kaggle Notebook/Kernel execution
- Kaggle competition submission
- Real-time streaming from Kaggle

## User Stories

### US-1: Authenticate with Kaggle

> As a user, I want to enter my Kaggle API credentials so that I can access Kaggle datasets from Data-Forge.

**Acceptance Criteria:**

1. Settings page has a "Kaggle" section with fields for `kaggle_username` and `kaggle_api_key`.
2. Credentials are stored encrypted in `AppSettings` (same pattern as `openrouter_api_key`).
3. A "Test Connection" button validates credentials against Kaggle API and shows success/failure.
4. Credentials persist across sessions.

### US-2: Browse and Search Kaggle Datasets

> As a user, I want to search Kaggle datasets by keyword, sort by popularity/recency, and preview metadata before importing.

**Acceptance Criteria:**

1. New "Kaggle" tab in the datasource creation flow (`/datasources/new`).
2. Search input with debounced query (300ms) hitting Kaggle dataset list API.
3. Results show: dataset title, owner, size, file count, last updated, usability score, download count.
4. Pagination with infinite scroll or page-based navigation.
5. Clicking a result shows expanded metadata: description, column names (if available), license, tags.

### US-3: Ingest Kaggle Dataset as Datasource

> As a user, I want to select a Kaggle dataset (and optionally a specific file within it) and import it as a Data-Forge datasource.

**Acceptance Criteria:**

1. After selecting a dataset, user sees file listing within the dataset.
2. User can select one or more files to import (each becomes a separate datasource).
3. Import triggers background download via Kaggle API → saved to `DATA_DIR/uploads/<namespace>/`.
4. Datasource created with `source_type: 'kaggle'` and metadata containing `kaggle_dataset_ref`, `kaggle_file`, `kaggle_version`.
5. Progress indicator during download.
6. On completion, datasource appears in datasource list with schema auto-detected.

### US-4: Re-ingest Updated Dataset Version

> As a user, I want to update a Kaggle-sourced datasource when the upstream dataset has a new version.

**Acceptance Criteria:**

1. Kaggle-sourced datasources show a "Check for Updates" action.
2. If newer version exists, show version diff (size change, date).
3. "Update" action downloads new version and creates a new snapshot (Iceberg append or overwrite based on build mode).
4. Previous data preserved via Iceberg time-travel.

## Technical Design

### Backend

#### New Module: `backend/modules/kaggle/`

```
modules/kaggle/
├── __init__.py
├── routes.py      # API endpoints
├── service.py     # Kaggle API client and business logic
├── schemas.py     # Pydantic request/response models
└── models.py      # DB model extensions (if needed)
```

#### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/kaggle/test` | Test Kaggle credentials |
| `GET` | `/api/v1/kaggle/datasets` | Search datasets (query, sort, page) |
| `GET` | `/api/v1/kaggle/datasets/{owner}/{dataset}` | Get dataset metadata and file list |
| `POST` | `/api/v1/kaggle/ingest` | Download and register dataset file as datasource |
| `GET` | `/api/v1/kaggle/ingest/{job_id}/status` | Poll ingest progress |
| `POST` | `/api/v1/kaggle/check-update` | Check if newer version exists for a datasource |

#### Kaggle API Integration

- Use the official Kaggle API (`https://www.kaggle.com/api/v1/`) with basic auth (`username:key`).
- Key endpoints consumed:
  - `GET /datasets/list` — search/browse
  - `GET /datasets/view/{owner}/{dataset}` — metadata
  - `GET /datasets/download/{owner}/{dataset}/{file}` — file download
  - `GET /datasets/status/{owner}/{dataset}` — version info
- All calls via `httpx.AsyncClient` with configurable timeout (default 120s for downloads).

#### Data Model Changes

Extend `AppSettings`:

```python
kaggle_username: str = ""
kaggle_api_key: str = ""
```

Extend `DataSource` metadata to support:

```python
# Stored in datasource metadata JSON field
{
    "kaggle_dataset_ref": "owner/dataset-name",
    "kaggle_file": "train.csv",
    "kaggle_version": 3,
    "kaggle_last_checked": "2026-01-15T10:30:00Z"
}
```

#### Ingest Flow

```
1. User selects dataset + file
2. POST /api/v1/kaggle/ingest
   ├─ Validate credentials
   ├─ Start background download task
   ├─ Return job_id immediately
3. Background task:
   ├─ Download file via Kaggle API → temp location
   ├─ Detect format (csv/parquet/json) from extension
   ├─ Move to DATA_DIR/uploads/<namespace>/
   ├─ Create DataSource record (source_type='kaggle', metadata with kaggle refs)
   ├─ Auto-detect schema via Polars scan
   └─ Mark job complete
4. Frontend polls GET /status/{job_id} for progress
```

### Frontend

#### Settings Integration

- Add Kaggle credentials section to existing Settings page.
- Fields: `kaggle_username` (text), `kaggle_api_key` (password with show/hide toggle).
- "Test Connection" button with success/error feedback.

#### Datasource Creation Flow

- Add "Kaggle" option to `/datasources/new` alongside existing "Upload", "Database" options.
- New component: `KaggleDatasetBrowser.svelte`
  - Search bar with sort dropdown (relevance, hottest, newest, most votes).
  - Results list with dataset cards.
  - Detail panel showing dataset files with sizes.
  - "Import" button per file.

#### Datasource List

- Kaggle-sourced datasources show Kaggle icon badge.
- "Check for Updates" action in context menu for Kaggle datasources.

### Dependencies

| Package | Version | Ecosystem | Purpose |
|---------|---------|-----------|---------|
| None | — | — | Use `httpx` (already in project) for Kaggle API calls |

No new dependencies required. The Kaggle REST API is consumed directly via HTTP.

### Security Considerations

- Kaggle API key stored encrypted at rest (same mechanism as other API keys in `AppSettings`).
- API key never exposed in frontend responses — backend proxies all Kaggle requests.
- Downloaded files go through existing datasource validation (size limits, format checks).
- Rate limiting: respect Kaggle API rate limits (add exponential backoff with jitter).

## Migration

- Alembic migration to add `kaggle_username` and `kaggle_api_key` columns to `app_settings` table.
- No data migration needed — new fields have empty-string defaults.

## Rollout Plan

| Phase | Scope | Duration |
|-------|-------|----------|
| 1 | Backend: Kaggle API client, settings, test endpoint | 2 days |
| 2 | Backend: Search, metadata, ingest endpoints | 3 days |
| 3 | Frontend: Settings, dataset browser, ingest UI | 3 days |
| 4 | Frontend: Update checking, provenance display | 2 days |
| 5 | Testing, edge cases, error handling | 2 days |

## Open Questions

1. Should we support Kaggle competition datasets (which have different API endpoints and terms)?
2. Should ingest be async (background task) or synchronous for small files?
3. Do we want to support Kaggle dataset search from the main datasource list (global search) or only from the dedicated creation flow?
