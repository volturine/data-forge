# PRD: Duplicate Analysis

## Overview

Add first-class analysis duplication so a user can clone an existing analysis with the same inputs, tab graph, and transform logic, while regenerating all output identities so the clone never overlaps with the source analysis's managed outputs.

This is a narrower, implementation-focused follow-up to the clone concept mentioned in [docs/prd/new-analysis-creation-flow.md](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/docs/prd/new-analysis-creation-flow.md). The product requirement here is explicit: duplicate the whole analysis, keep the same input datasources and transformations, and make the outputs safe and isolated.

Tab-only duplication is intentionally handled separately in [duplicate-analysis-tab.md](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/docs/prd/duplicate-analysis-tab.md).

## Problem Statement

Users currently have no dedicated way to duplicate an analysis they want to reuse as a starting point for a new branch of work. Rebuilding an equivalent analysis manually is slow and error-prone:

1. Recreating multiple tabs and steps by hand wastes time.
2. Rewiring same-analysis derived tabs is easy to get wrong.
3. Reusing the original `output.result_id` values would collide with existing managed output datasources.
4. Reusing the original output table naming can also create confusing or unsafe overlap when the clone is built.

The product needs a safe duplication flow that preserves analytical logic but guarantees new output ownership.

## Goals

| # | Goal | Success Metric |
|---|------|----------------|
| G-1 | Duplicate an analysis in one action | User can create a clone from gallery or editor in under 10 seconds |
| G-2 | Preserve analytical logic exactly | Duplicated tabs and steps match the source analysis semantics |
| G-3 | Prevent output overlap | Clone always receives new output IDs before persistence |
| G-4 | Preserve internal tab chaining | Derived tabs still point to the duplicated upstream tab outputs |
| G-5 | Keep user intent obvious | Clone naming and output naming clearly indicate a new independent analysis |

## Non-Goals

- Remapping input datasources during duplication
- Copying build history, run history, or version history
- Copying schedules automatically
- Partial duplication of selected tabs only
- Backward-compatible legacy clone paths

## User Stories

### US-1: Duplicate the Entire Analysis

> As a user, I want to duplicate an existing analysis so I can branch my work without rebuilding the same logic from scratch.

**Acceptance Criteria:**

1. A duplicate action exists in the analysis gallery and analysis editor.
2. Duplicate opens a lightweight dialog with editable name and optional description.
3. Default name is `Copy of {original}`.
4. The created clone contains the same number of tabs and steps as the source analysis.
5. The clone opens in the analysis editor immediately after creation.

### US-2: Preserve Inputs and Transform Logic

> As a user, I want the duplicate to keep the same input datasources, branches, and transform steps.

**Acceptance Criteria:**

1. For tabs sourcing external datasources, `datasource.id` and datasource config are copied as-is.
2. All step types, configs, order, and dependency edges are preserved.
3. The duplicate is semantically equivalent to the source analysis before any user edits.

### US-3: Regenerate Outputs Safely

> As a user, I need the duplicate to produce new outputs so it cannot overwrite or conflict with the source analysis.

**Acceptance Criteria:**

1. Every duplicated tab receives a fresh UUID v4 `output.result_id`.
2. Any derived tab whose datasource points to another tab's `output.result_id` is rewritten to point at the duplicated upstream output ID.
3. `datasource.analysis_tab_id` for derived tabs is rewritten to the duplicated upstream tab ID.
4. Output datasource ownership is created under the new analysis only.
5. The source analysis keeps all of its existing output datasource ownership unchanged.

### US-4: Avoid Storage-Level Ambiguity

> As a user, I want duplicated outputs to be clearly separate, not just internally separate.

**Acceptance Criteria:**

1. Duplicate flow regenerates default output names and `iceberg.table_name` values with a safe suffix derived from the new analysis name.
2. Users may edit output names after duplication in the editor.
3. Default behavior must prefer isolation over preserving the original display names exactly.

### US-5: Do Not Clone Operational Side Effects

> As a user, I want the duplicate to copy the recipe, not the operational history.

**Acceptance Criteria:**

1. Build history is not copied.
2. Schedules are not copied.
3. Existing notifications and output monitoring state are not re-triggered during duplication.
4. Duplicate creation is metadata-only until the user explicitly builds the cloned analysis.

## Technical Design

### Backend

#### New Endpoint

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/analysis/{analysis_id}/duplicate` | Duplicate a full analysis with regenerated outputs |

#### Request Schema

```python
class DuplicateAnalysisSchema(BaseModel):
    name: str
    description: str | None = None
```

#### Duplication Rules

1. Deep-copy the source `pipeline_definition`.
2. Regenerate identifiers in this order:
   - new analysis ID from persistence layer
   - new tab IDs for every duplicated tab
   - new step IDs for every duplicated step
   - new `output.result_id` for every duplicated tab
3. Rewrite internal references:
   - `datasource.analysis_tab_id` must point to the duplicated tab ID
   - `datasource.id` for same-analysis derived tabs must point to the duplicated upstream `output.result_id`
   - `depends_on` step references must point to duplicated step IDs
4. Regenerate default output naming:
   - `output.filename`
   - `output.iceberg.table_name`
5. Persist via the same validation path as normal analysis creation.

#### Service Sketch

```python
async def duplicate_analysis(
    session: AsyncSession,
    analysis_id: str,
    data: DuplicateAnalysisSchema,
) -> Analysis:
    original = await get_analysis(session, analysis_id)
    pipeline = deepcopy(original.pipeline_definition)

    tab_id_map: dict[str, str] = {}
    output_id_map: dict[str, str] = {}

    for tab in pipeline["tabs"]:
        old_tab_id = tab["id"]
        new_tab_id = str(uuid4())
        tab_id_map[old_tab_id] = new_tab_id
        tab["id"] = new_tab_id

        old_output_id = tab["output"]["result_id"]
        new_output_id = str(uuid4())
        output_id_map[old_output_id] = new_output_id
        tab["output"]["result_id"] = new_output_id

    for tab in pipeline["tabs"]:
        datasource = tab["datasource"]
        upstream_tab_id = datasource.get("analysis_tab_id")
        if upstream_tab_id:
            datasource["analysis_tab_id"] = tab_id_map[upstream_tab_id]
            datasource["id"] = output_id_map[datasource["id"]]

        tab["output"] = regenerate_output_config(
            output=tab["output"],
            analysis_name=data.name,
            tab_name=tab["name"],
        )

    return await create_analysis(
        session,
        AnalysisCreateSchema(
            name=data.name,
            description=data.description or original.description,
            tabs=pipeline["tabs"],
        ),
    )
```

#### Validation Contract

- Duplicate must fail fast if any source tab has invalid `output.result_id`.
- Duplicate must fail fast if an internal `analysis_tab_id` points to a missing tab.
- Duplicate must not silently preserve stale output IDs.
- Duplicate uses the same output datasource conflict checks as normal create.

### Frontend

#### Entry Points

1. Gallery card overflow action: `Duplicate`
2. Analysis editor overflow action: `Duplicate analysis`

#### Duplicate Dialog

Fields:

- `Name`
- `Description`
- Read-only summary: tabs count, step count, input datasource count
- Note: "Outputs will be regenerated and will not reuse the original analysis outputs."

#### UX Rules

1. Duplicate is optimistic only after the API succeeds.
2. On success, route directly to the cloned analysis editor.
3. On failure, show explicit validation reason from the backend.
4. No hidden auto-build after duplication.

## Data Contract

### Source Analysis Fields Preserved

- `name` only as input to default clone name
- `description`
- `pipeline_definition.tabs[*].name`
- `pipeline_definition.tabs[*].datasource` for external sources
- `pipeline_definition.tabs[*].steps`

### Fields Regenerated

- Analysis ID
- Tab IDs
- Step IDs
- `output.result_id`
- Default `output.filename`
- Default `output.iceberg.table_name`

### Fields Not Copied

- Build records
- Locks
- Schedules
- Historical versions

## Migration

- No database migration required.
- Existing analysis model remains unchanged.
- Feature is additive through a new endpoint and UI action.

## Rollout Plan

| Phase | Scope | Duration |
|-------|-------|----------|
| 1 | Backend duplicate service and route | 1 day |
| 2 | Validation and output regeneration rules | 1 day |
| 3 | Frontend duplicate actions and dialog | 1 day |
| 4 | Tests: external-input tabs, derived tabs, multi-tab graphs | 1 day |

## Open Questions

1. Should duplicated analyses preserve the original output labels in the UI while still regenerating storage names underneath?
2. Should duplication be allowed from a historical analysis version, or only the latest saved analysis?
3. Should output notifications be copied as disabled defaults, or omitted entirely on first release?
