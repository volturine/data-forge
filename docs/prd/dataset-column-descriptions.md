# PRD: Dataset Column Descriptions

## Overview

Add first-class per-column descriptions so users and AI agents can explain what each dataset column means, what it is used for, and any important semantic caveats.

For product language, this document uses **dataset**. In the current codebase, the runtime model is a **datasource**.

## Problem Statement

Dataset columns currently expose only structural metadata such as column name, dtype, nullability, and sample value. That is enough to render schema, but not enough to capture meaning.

Today the app is missing a durable place to store answers to questions like:

- What does this column represent?
- Is this a business key, display label, or internal ID?
- What unit, currency, timezone, or convention does it use?
- Is the column safe for AI-generated joins, filters, or aggregations?

Without first-class column descriptions:

1. Users must keep column meaning in their heads or external docs.
2. AI cannot reliably ingest dataset semantics from the app itself.
3. Schema views remain structural instead of informative.
4. Column intent is lost when a dataset is handed off between teammates.

## Goals

| # | Goal | Success Metric |
|---|------|----------------|
| G-1 | Persist a description for each active dataset column | Any column can store a user-authored description |
| G-2 | Make descriptions readable by AI and UI | API responses include column descriptions in standard schema reads |
| G-3 | Make descriptions editable by users and AI | UI and API both support create/update/clear flows |
| G-4 | Keep schema and descriptions aligned | Description remains attached when a column with the same name still exists after schema refresh |
| G-5 | Improve schema browsing | Dataset schema views display descriptions inline, not in external docs |

## Non-Goals

- Automatic description generation in v1
- Bulk glossary/tagging/taxonomy support beyond a plain description field
- Column-level permissions separate from datasource permissions
- Versioned history of every description edit in v1

## User Stories

### US-1: View Column Meaning in Schema UI

> As a user, I want to read a description beside each dataset column so I can understand the dataset without opening outside documentation.

**Acceptance Criteria:**

1. The schema table shows a `Description` column.
2. Long descriptions are truncated in-table and expandable.
3. Empty descriptions render a clear empty state such as `No description`.
4. Column stats/details panels also show the description.

### US-2: Edit a Column Description

> As a user, I want to add or update a column description so the dataset captures business meaning, not just technical schema.

**Acceptance Criteria:**

1. A user can edit a description from the schema UI.
2. Saving a description updates the backend immediately.
3. Clearing the field removes the stored description.
4. The UI shows save/error state clearly.

### US-3: AI Can Read and Write Column Descriptions

> As an AI agent, I need column descriptions in normal app contracts so I can use them for reasoning and update them when asked.

**Acceptance Criteria:**

1. Standard datasource/schema read APIs return column descriptions.
2. A documented write path exists for updating one or more column descriptions.
3. The same fields are available through MCP-exposed tools or other AI-facing API surfaces.
4. Descriptions are plain text and not hidden inside opaque blobs.

### US-4: Descriptions Survive Schema Refreshes

> As a user, I want my column descriptions to remain when the dataset schema refreshes and the column still exists.

**Acceptance Criteria:**

1. If a column name still exists after schema refresh, its description is preserved.
2. If a column is removed from the active schema, its description is no longer shown in the default schema UI.
3. Description persistence must not require mutating raw schema cache payloads by hand.

## Technical Design

### Backend

Use a first-class persistence model for column metadata rather than storing descriptions inside ad hoc frontend state.

#### Proposed Model

```python
class DataSourceColumnMetadata(SQLModel, table=True):
    id: str
    datasource_id: str
    column_name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
```

#### Contract Rules

1. Uniqueness is `(datasource_id, column_name)`.
2. `description` is nullable; empty string is normalized to `null`.
3. Standard datasource schema responses join structural schema with metadata.
4. Schema refresh preserves descriptions for columns whose names still match.
5. Removed columns are omitted from default schema responses.

#### API Additions

Preferred shape:

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/datasource/{id}/schema` | Return schema with per-column description |
| `PATCH` | `/api/v1/datasource/{id}/column-metadata` | Batch update column descriptions |

Suggested request schema:

```python
class ColumnDescriptionPatch(BaseModel):
    column_name: str
    description: str | None

class BatchColumnDescriptionUpdate(BaseModel):
    columns: list[ColumnDescriptionPatch]
```

Suggested response shape:

```python
class DataSourceColumnSchema(BaseModel):
    name: str
    dtype: str
    nullable: bool
    sample_value: str | None
    description: str | None
```

### Frontend

#### Schema Table

Update the datasource schema tab to show:

- `#`
- `Column`
- `Type`
- `Description`

#### Editing UX

1. Inline edit action per row, or a side panel triggered from the selected column.
2. Multi-line text input for description.
3. Save/cancel controls.
4. Optimistic refresh of the schema row after save.

#### AI Surfaces

- Any frontend state used to assemble AI context for a datasource must include column descriptions.
- Column descriptions must be available in the same normalized TS type that describes schema rows.

## Data Quality Rules

- Descriptions are plain text.
- Leading/trailing whitespace is trimmed.
- Maximum length: 2,000 characters.
- Markdown is not required in v1; render as plain text.
- HTML is not supported.

## Rollout Plan

| Phase | Scope |
|-------|-------|
| 1 | Add persistence model and migration |
| 2 | Return descriptions from datasource schema APIs |
| 3 | Add column description editing to schema UI |
| 4 | Expose the same fields to AI-facing tool surfaces |
| 5 | Add tests for schema refresh preservation and edit flows |

## Acceptance Criteria

- [ ] Every active dataset column can store a nullable description
- [ ] Datasource schema responses include `description` per column
- [ ] Users can edit column descriptions from the schema UI
- [ ] AI-facing read/write contracts can ingest and update descriptions
- [ ] Descriptions persist across schema refresh when column names remain stable
- [ ] Removed columns do not appear with stale descriptions in the default schema view
- [ ] `just verify` passes
