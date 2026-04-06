# PRD: Analytical Dashboards

## Overview

Add analytical dashboards as a first-class layer on top of analyses. Dashboards let users define configurable variables, bind those variables into analysis logic for filters and similar controls, and assemble interactive runtime views from dataset previews and charts for real-world decision-making.

This is not a separate BI product. The dashboard is a runtime surface for an existing analysis: the analysis remains the source of truth for data logic, and the dashboard exposes controlled interactivity on top of it.

## Problem Statement

The current product supports building analyses and previewing data inside the editor, but it does not provide a configurable runtime for decision support:

1. Users cannot define reusable analysis-level variables such as region, date range, channel, or threshold.
2. Filters and related step configs cannot be driven by user-configurable runtime inputs.
3. Dataset previews and charts exist only as authoring-time feedback, not as durable dashboard widgets.
4. There is no interactive dashboard surface where end users can explore results without editing the pipeline itself.

This leaves a gap between building data logic and actually using it in day-to-day analytical workflows.

## Goals

| # | Goal | Success Metric |
|---|------|----------------|
| G-1 | Add analysis-scoped variables | Users can configure typed variables and reuse them across dashboard widgets and analysis logic |
| G-2 | Support interactive filtering | Variable changes update relevant widgets within 2 seconds for typical datasets |
| G-3 | Make previews and charts durable | Users can save table preview and chart widgets into a dashboard layout |
| G-4 | Keep analysis as source of truth | Dashboard uses existing analysis tabs and transformations, not a separate query model |
| G-5 | Support real-world decision use | Dashboards are configurable, shareable inside the app, and safe for repeated operational use |

## Non-Goals

- Full external BI embedding
- Freeform SQL editor for dashboard users
- Cross-analysis dashboards in the first release
- Pixel-perfect slide or presentation tooling
- Legacy dashboard compatibility paths

## User Stories

### US-1: Define Variables Once Per Analysis

> As an analyst, I want to define reusable variables like date range, region, and product line so the analysis can respond to runtime decisions.

**Acceptance Criteria:**

1. An analysis can define typed variables:
   - string
   - number
   - boolean
   - single select
   - multi select
   - date
   - date range
2. Each variable has:
   - stable ID
   - label
   - type
   - default value
   - required flag
   - optional allowed values or datasource-backed options
3. Variables are stored inside the analysis definition and versioned with it.

### US-2: Use Variables Inside Analysis Logic

> As an analyst, I want to use dashboard variables inside filters and similar step configs without hardcoding values.

**Acceptance Criteria:**

1. Step configs can reference variables through an explicit typed binding model, not raw string interpolation.
2. Variable bindings are validated server-side against the target step schema.
3. Filter-like steps can use variables for equality, inclusion, numeric thresholds, and date boundaries.
4. Invalid variable usage blocks save and returns a clear validation error.

### US-3: Build Interactive Dashboard Layouts

> As an analyst, I want to turn analysis outputs into a configurable dashboard with previews and graphs.

**Acceptance Criteria:**

1. A dashboard belongs to one analysis.
2. A dashboard can contain these widget types in v1:
   - dataset preview
   - chart
   - metric KPI
   - text header
3. Each widget binds to a tab output from the owning analysis.
4. Layout is configurable with resize and reorder support.
5. Dashboard configuration is saved with the analysis.

### US-4: Interact Without Editing the Analysis

> As a dashboard user, I want to change variables and explore the data without entering edit mode for the analysis.

**Acceptance Criteria:**

1. Dashboard runtime presents controls for variables at the top or in a side panel.
2. Changing a variable refreshes only affected widgets.
3. Dataset preview widgets support sorting, pagination, and optional local search.
4. Chart widgets support hover, legend toggles, and selection-driven filtering when configured.
5. Runtime users cannot mutate pipeline structure from the dashboard screen.

### US-5: Use Dashboards for Real Operational Decisions

> As a business user, I want dashboards that remain understandable, configurable, and trustworthy for repeated decision-making.

**Acceptance Criteria:**

1. Each widget shows source tab, last refresh time, and variable state used for the current result.
2. Dashboards support empty-state and error-state messaging at widget level.
3. Runtime values are encoded in the URL so views are shareable and reproducible.
4. Dashboard refresh must be explicit and observable, not silently stale.

## Product Model

### Core Principle

The analysis owns the computation. The dashboard owns presentation and interaction. Variables bridge the two.

### New Analysis-Level Objects

```json
{
  "tabs": [],
  "variables": [],
  "dashboards": []
}
```

#### Variable Definition

```json
{
  "id": "region",
  "label": "Region",
  "type": "single_select",
  "default_value": "emea",
  "required": true,
  "options": [
    { "label": "EMEA", "value": "emea" },
    { "label": "AMER", "value": "amer" }
  ]
}
```

#### Dashboard Definition

```json
{
  "id": "sales-overview",
  "name": "Sales Overview",
  "description": "Interactive view of sales performance",
  "layout": [],
  "widgets": []
}
```

## Technical Design

### Backend

#### New/Updated Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `PUT` | `/api/v1/analysis/{analysis_id}` | Save variables and dashboards as part of analysis payload |
| `GET` | `/api/v1/analysis/{analysis_id}/dashboards/{dashboard_id}` | Get dashboard config and variable definitions |
| `POST` | `/api/v1/analysis/{analysis_id}/dashboards/{dashboard_id}/run` | Execute dashboard widgets for a given variable state |
| `POST` | `/api/v1/analysis/{analysis_id}/dashboards/validate` | Validate variable bindings and widget config |

#### Variable Binding Contract

Variables are referenced explicitly inside supported step configs:

```json
{
  "operator": "in",
  "column": "region",
  "value": {
    "kind": "variable_ref",
    "variable_id": "region"
  }
}
```

Rules:

1. Backend resolves variable refs into concrete values before compute.
2. Resolution is typed and schema-aware.
3. Variable refs are allowed only in fields declared variable-capable by the step schema.
4. Raw expression injection through variable values is forbidden.

#### Dashboard Run Flow

```python
async def run_dashboard(
    session: AsyncSession,
    analysis_id: str,
    dashboard_id: str,
    variable_values: dict[str, object],
) -> DashboardRunResult:
    analysis = await get_analysis(session, analysis_id)
    dashboard = find_dashboard(analysis, dashboard_id)
    validate_variable_values(analysis.variables, variable_values)

    resolved_pipeline = apply_variable_values(
        pipeline=analysis.pipeline_definition,
        variable_values=variable_values,
    )

    widget_results = await compute_widgets(
        analysis_id=analysis_id,
        dashboard=dashboard,
        pipeline=resolved_pipeline,
    )
    return DashboardRunResult(
        variable_state=variable_values,
        widgets=widget_results,
    )
```

#### Widget Sources

In v1, widgets can source from saved tab outputs only.

This constraint keeps the runtime predictable:

1. widget source contract stays stable
2. build lineage stays understandable
3. dashboard execution avoids ambiguous unsaved editor state

#### Widget Result Types

```python
class DatasetPreviewResult(BaseModel):
    columns: list[str]
    rows: list[dict[str, object]]
    row_count: int
    page: int
    page_size: int

class ChartResult(BaseModel):
    schema: dict[str, str]
    data: list[dict[str, object]]
    config: dict[str, object]

class MetricResult(BaseModel):
    label: str
    value: str | int | float
    comparison: str | int | float | None = None
```

#### Performance Rules

1. Dataset preview widgets are row-limited by default.
2. Widget runs are cached by:
   - analysis version
   - dashboard ID
   - widget ID
   - normalized variable state
3. Variable changes debounce on the frontend before execution.
4. Only affected widgets rerun when a variable changes.

### Frontend

#### New Screens

1. Dashboard builder inside the analysis editor
2. Dashboard runtime view for non-authoring usage

#### Builder Capabilities

1. Add/edit/remove variables
2. Bind variables into supported step configs
3. Add widgets from analysis tab outputs
4. Configure widget chart type, columns, labels, and interactions
5. Arrange dashboard layout with drag and resize

#### Runtime Capabilities

1. Variable control bar
2. Widget loading states
3. Widget-level errors
4. URL-synced variable state
5. Manual refresh action

## Security and Validation

1. Variable values are validated against declared type and allowed values.
2. Dashboard runtime cannot mutate the stored analysis.
3. Widget execution is limited to saved analyses, not unsaved local editor state.
4. Preview row limits and chart payload limits are enforced server-side.

## Migration

- No database migration required if `variables` and `dashboards` are stored inside `Analysis.pipeline_definition`.
- Existing analyses load with empty `variables` and `dashboards` arrays.
- Dashboard support is additive and does not change existing analysis execution for analyses that do not use variables.

## Rollout Plan

| Phase | Scope | Duration |
|-------|-------|----------|
| 1 | Analysis schema extension for variables and dashboards | 2 days |
| 2 | Variable binding validation and compute resolution | 3 days |
| 3 | Dashboard run endpoint and widget result contracts | 3 days |
| 4 | Frontend variable builder and binding UX | 3 days |
| 5 | Frontend dashboard builder and runtime | 4 days |
| 6 | Tests: variable validation, widget execution, URL state, interactivity | 3 days |

## Open Questions

1. Should datasource-backed variable options be computed from a saved output snapshot or live at runtime?
2. Which chart types are mandatory in v1 beyond bar, line, and area?
3. Should dashboard access follow analysis permissions exactly, or allow separate runtime-only sharing later?
