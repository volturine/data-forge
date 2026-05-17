# PRD: Dataset Descriptions

## Overview

Add a first-class dataset description field so every datasource can carry durable human and AI-readable context about what the dataset is, where it comes from, and how it should be used.

For product language, this document uses **dataset**. In the current codebase, the runtime model is a **datasource**.

## Problem Statement

Datasets currently have a name and technical metadata, but no durable description field. That makes it difficult to capture the purpose of a dataset inside the product.

Teams need to store answers to questions like:

- What business domain does this dataset represent?
- What is the intended use of this dataset?
- What are important caveats, freshness expectations, or join rules?
- Is this dataset user-facing, internal, experimental, or deprecated?

Without a dataset description:

1. Dataset intent is disconnected from the dataset record itself.
2. AI cannot ingest dataset purpose from the normal datasource contract.
3. Create and edit flows capture only a short label (`name`), not meaning.
4. Monitoring and lineage views lack contextual explanations for downstream consumers.

## Goals

| # | Goal | Success Metric |
|---|------|----------------|
| G-1 | Persist a description on every dataset | Datasource model supports nullable `description` |
| G-2 | Make the description visible in key UI surfaces | Create, detail, and list surfaces can display dataset description |
| G-3 | Make the description editable after creation | Users can update it without re-creating the dataset |
| G-4 | Make the description AI-ingestable and AI-editable | Standard API contracts expose read/write support |
| G-5 | Keep naming and description separate | `name` remains the label; `description` holds longer context |

## Non-Goals

- Rich-text editing in v1
- Dataset-level tags, ownership overhaul, or governance workflows
- Auto-generated descriptions in v1
- Description version history in v1

## User Stories

### US-1: Add Description During Dataset Creation

> As a user, I want to add a description when I create a dataset so its purpose is captured immediately.

**Acceptance Criteria:**

1. Dataset creation forms include an optional `Description` field.
2. The field supports multi-line plain text.
3. The description is stored on successful create.
4. Leaving it blank is valid.

### US-2: Edit Description on an Existing Dataset

> As a user, I want to update a dataset description later as the dataset's purpose or usage guidance changes.

**Acceptance Criteria:**

1. Dataset settings/general UI includes an editable description field.
2. Saving updates the persisted datasource record.
3. Clearing the field removes the description.
4. The UI shows save and error states clearly.

### US-3: Read Description in Browsing Surfaces

> As a user, I want to see dataset descriptions where I browse or inspect datasets so I can choose the right data source quickly.

**Acceptance Criteria:**

1. Dataset detail/general view shows the full description.
2. Dataset lists show either a short preview or an explicit access point such as tooltip/details expansion.
3. Empty descriptions show a clear empty state.

### US-4: AI Can Use Dataset Descriptions

> As an AI agent, I need dataset descriptions in the normal datasource contract so I can use them when recommending joins, transformations, or schedules.

**Acceptance Criteria:**

1. Datasource list and detail responses include `description`.
2. Datasource create and update contracts accept `description`.
3. AI-facing tool surfaces expose the same field directly.
4. The description is stored as plain text, not buried in config blobs.

## Technical Design

### Backend

Add a nullable `description` field directly to the datasource model.

#### Proposed Model Change

```python
class DataSource(SQLModel, table=True):
    id: str
    name: str
    description: str | None = None
    source_type: str
    ...
```

#### API Contract Changes

```python
class DataSourceCreateSchema(BaseModel):
    name: str
    description: str | None = None
    ...

class DataSourceUpdateSchema(BaseModel):
    name: str | None = None
    description: str | None = None
    ...

class DataSourceResponse(BaseModel):
    id: str
    name: str
    description: str | None
    ...
```

#### Rules

- Empty string is normalized to `null`.
- Description is plain text.
- Maximum length: 4,000 characters.
- Description must be included in list, get, create, and update contracts.

### Frontend

#### Create Flows

Add `Description` inputs to:

1. File upload datasource creation
2. Database connection datasource creation
3. Any future datasource creation form variants

#### Edit Flows

Add a dataset description editor to the datasource general/config panel.

#### Display Rules

1. Detail page shows the full description.
2. List views show a concise preview or tooltip.
3. Description is visually distinct from `Name`, `Type`, and provenance metadata.

### AI Surfaces

- Any MCP/tool wrapper that returns datasource details must expose `description` directly.
- Any AI write path for datasource metadata must support updating `description` without requiring unrelated config edits.

## Migration

- Add nullable `description` column to datasource table.
- Backfill existing rows as `null`.
- No legacy compatibility path is required beyond treating missing values as empty.

## Rollout Plan

| Phase | Scope |
|-------|-------|
| 1 | Add datasource migration and backend schema updates |
| 2 | Thread description through datasource service and API responses |
| 3 | Add create/edit/display support in frontend datasource surfaces |
| 4 | Expose description in AI-facing tool contracts |
| 5 | Add tests for create, update, list, and detail views |

## Acceptance Criteria

- [ ] Datasource model supports nullable `description`
- [ ] Datasource create and update APIs accept `description`
- [ ] Datasource list and detail APIs return `description`
- [ ] Dataset creation forms include a description field
- [ ] Dataset detail/settings surfaces support editing description
- [ ] AI-facing read/write contracts expose the same field directly
- [ ] `just verify` passes
