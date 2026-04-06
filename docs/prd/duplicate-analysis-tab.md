# PRD: Duplicate Analysis Tab

## Overview

Add first-class tab duplication inside an existing analysis. A duplicated tab keeps the same input source and transformation logic as the source tab, but receives a new tab identity and a new output identity so it can evolve independently without overlapping outputs.

This is a separate feature from:

- whole-analysis duplication in [duplicate-analysis.md](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/docs/prd/duplicate-analysis.md)
- downstream chaining via `POST /api/v1/analysis/{analysis_id}/tabs/{tab_id}/derive`, which creates a new derived tab with fresh empty logic rather than copying the tab

## Problem Statement

Users need a fast way to branch one tab inside an analysis without cloning the entire analysis and without rebuilding the same transform steps by hand.

Current gaps:

1. `derive` creates a new downstream tab, but does not copy the existing transform logic.
2. Whole-analysis duplication is too large when the user only wants to branch one tab.
3. Manual tab recreation is slow and error-prone, especially when the tab has many steps or depends on another tab.
4. Reusing the original `output.result_id` would collide with the existing managed output datasource.

The product needs a true tab duplication action that creates a sibling branch of work inside the same analysis.

## Goals

| # | Goal | Success Metric |
|---|------|----------------|
| G-1 | Duplicate a tab in one action | User can branch a tab from the editor in under 5 seconds |
| G-2 | Preserve tab logic exactly | New tab contains the same datasource config, steps, and step dependencies |
| G-3 | Prevent output overlap | New tab always gets a fresh `output.result_id` before save |
| G-4 | Keep dependency behavior predictable | Existing downstream tabs are never silently rewired |
| G-5 | Support iterative branching | Users can duplicate both source tabs and derived tabs |

## Non-Goals

- Duplicating multiple selected tabs in one action
- Automatically cloning downstream child tabs
- Automatically rewiring existing child tabs to the duplicate
- Remapping input datasources during duplication
- Cross-analysis movement of the duplicated tab

## User Stories

### US-1: Duplicate a Source Tab

> As a user, I want to duplicate a tab that starts from an external datasource so I can try a variant of the same transformation logic.

**Acceptance Criteria:**

1. A `Duplicate tab` action exists in the tab UI.
2. The duplicated tab is created in the same analysis.
3. The new tab copies:
   - `datasource.id`
   - `datasource.config`
   - all steps
   - tab-level output settings except regenerated output identity/name fields
4. The new tab gets a fresh `id` and fresh `output.result_id`.
5. The duplicated tab appears adjacent to the source tab in the tab strip.

### US-2: Duplicate a Derived Tab

> As a user, I want to duplicate a tab that depends on another tab so I can branch that derived logic too.

**Acceptance Criteria:**

1. If the source tab has `datasource.analysis_tab_id`, the duplicate keeps pointing to the same upstream tab.
2. The duplicate does not clone the upstream parent automatically.
3. The duplicate keeps the same same-analysis datasource contract:
   - `datasource.analysis_tab_id` remains the same upstream tab ID
   - `datasource.id` remains the upstream tab's `output.result_id`
4. The duplicated tab still gets its own new `output.result_id`.

### US-3: Preserve Step Logic Safely

> As a user, I want the duplicated tab to behave like the original until I change it.

**Acceptance Criteria:**

1. All duplicated steps receive fresh step IDs.
2. Intra-tab `depends_on` references are rewritten to the duplicated step IDs.
3. Step config is deep-copied.
4. Cross-tab source references inside step config remain unchanged by default.

### US-4: Do Not Surprise Existing Dependents

> As a user, I do not want existing downstream tabs to change behavior when I duplicate a tab.

**Acceptance Criteria:**

1. Existing tabs that currently depend on the source tab continue pointing to the original source tab.
2. Duplication does not rewrite any other tab automatically.
3. If the user wants downstream tabs to point to the duplicate, they must rewire them explicitly.

### US-5: Keep Outputs Independent

> As a user, I want the duplicated tab to build to its own output dataset and table identity.

**Acceptance Criteria:**

1. Duplicate regenerates `output.result_id`.
2. Duplicate regenerates default `output.filename`.
3. Duplicate regenerates default `output.iceberg.table_name` when present.
4. Duplicate is metadata-only until the user builds.

## Product Behavior

### Core Principle

Tab duplication creates a sibling branch, not a derived child and not a replacement.

### Placement

The duplicated tab is inserted immediately after the source tab in the tab order.

### Naming

Default naming:

- first duplicate: `{original} Copy`
- subsequent duplicates: `{original} Copy 2`, `{original} Copy 3`, etc.

### Dependency Semantics

#### Case 1: Source tab uses external datasource

The duplicate keeps the same external datasource and branch/snapshot config.

#### Case 2: Source tab is derived from another tab

The duplicate keeps the same upstream tab dependency. It becomes another sibling consumer of that upstream tab's output.

#### Case 3: Other tabs depend on the source tab

Those tabs stay attached to the original source tab. No automatic cascade duplication or rewiring occurs in v1.

## Technical Design

### Backend

#### New Endpoint

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/analysis/{analysis_id}/tabs/{tab_id}/duplicate` | Duplicate a single tab inside the same analysis |

#### Request Schema

```python
class DuplicateTabBody(BaseModel):
    name: str | None = None
```

#### Duplication Rules

1. Load the analysis and locate the source tab.
2. Generate:
   - a new tab ID
   - new step IDs for every duplicated step
   - a new `output.result_id`
3. Preserve:
   - source tab `datasource.id`
   - source tab `datasource.analysis_tab_id`
   - source tab `datasource.config`
   - step order
   - step config values
4. Rewrite:
   - duplicated tab `id`
   - duplicated steps `id`
   - duplicated steps `depends_on`
   - duplicated output identity and default names
5. Insert the new tab immediately after the source tab.
6. Persist through the normal analysis validation/update path.

#### Service Sketch

```python
def duplicate_tab(
    session: Session,
    analysis_id: str,
    tab_id: str,
    name: str | None = None,
) -> PipelineTab:
    analysis = session.get(Analysis, analysis_id)
    pipeline = analysis.pipeline
    source = pipeline.find_tab(tab_id)

    new_tab_id = f"tab-{uuid.uuid4()}"
    step_id_map: dict[str, str] = {}

    duplicated_steps = []
    for step in source.steps:
        new_step_id = str(uuid.uuid4())
        step_id_map[step.id] = new_step_id
        duplicated_steps.append(
            PipelineStep(
                id=new_step_id,
                type=step.type,
                config=deepcopy(step.config),
                depends_on=[],
                is_applied=step.is_applied,
            )
        )

    for duplicated, source_step in zip(duplicated_steps, source.steps, strict=True):
        duplicated.depends_on = [step_id_map[dep_id] for dep_id in source_step.depends_on]

    new_tab = PipelineTab(
        id=new_tab_id,
        name=name or next_duplicate_name(pipeline.tabs, source.name),
        parent_id=source.parent_id,
        datasource=deepcopy(source.datasource),
        output=regenerate_output_config(
            output=deepcopy(source.output),
            output_id=str(uuid.uuid4()),
            tab_name=name or source.name,
        ),
        steps=duplicated_steps,
    )

    insert_after_tab(pipeline.tabs, source.id, new_tab)
    save_pipeline(session, analysis, pipeline)
    return new_tab
```

#### Validation Contract

- Duplicate must fail if the source tab does not exist.
- Duplicate must fail if any duplicated `depends_on` reference cannot be rewritten.
- Duplicate must always emit a UUID v4 `output.result_id`.
- Duplicate must preserve the existing same-analysis datasource rule:
  - when `datasource.analysis_tab_id` is present, `datasource.id` must still equal the upstream tab's `output.result_id`

### Frontend

#### Entry Point

- Tab context menu or tab overflow menu action: `Duplicate tab`

#### UX Rules

1. Duplicate is single-click by default.
2. If no custom name is provided, frontend may omit the request body and let backend assign the next default copy name.
3. After duplication, the editor switches focus to the duplicated tab.
4. A small non-modal toast confirms that the tab has independent outputs.

#### No Dialog Requirement

Unlike whole-analysis duplication, tab duplication should not require a blocking dialog in v1. Speed matters more than pre-configuration here.

## Data Contract

### Preserved Fields

- `parent_id`
- `datasource.id`
- `datasource.analysis_tab_id`
- `datasource.config`
- step types
- step configs
- step order

### Regenerated Fields

- tab `id`
- step `id`
- step `depends_on` references
- `output.result_id`
- default `output.filename`
- default `output.iceberg.table_name`

### Unchanged External State

- other tabs in the analysis
- build history
- schedules
- datasource ownership of the source tab

## Migration

- No database migration required.
- Feature is additive through a new analysis-tab endpoint and editor action.

## Rollout Plan

| Phase | Scope | Duration |
|-------|-------|----------|
| 1 | Backend tab duplicate service and route | 1 day |
| 2 | Frontend tab action and focus behavior | 1 day |
| 3 | Tests: source tab, derived tab, downstream dependents unchanged | 1 day |

## Open Questions

1. Should duplicated tabs preserve `parent_id` exactly, or should duplicated tabs clear `parent_id` to better signal a sibling branch?
2. Should step configs that reference sibling tab IDs in fields like `right_source` or `sources` get optional remapping in a later release?
3. Should v1 allow rename-on-duplicate from a small inline popover, or keep duplication fully one-click?
