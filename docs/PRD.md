# Product Requirements Document (PRD)

## Document Control

- **Product:** Data-Forge Analysis Platform
- **Status:** Active
- **Last Updated:** 2026-02-23
- **Owner:** Product + Engineering

---

## 1. Problem Statement

Data teams need a local-first way to build, run, and monitor data transformations without writing full code pipelines. Existing tools are either too code-heavy or too cloud-coupled.

This product provides a visual, tab-based transformation workflow with reproducible outputs, scheduling, lineage, and run observability.

---

## 2. Product Vision

Enable users to design and operate end-to-end dataset pipelines visually while keeping execution and data storage local, auditable, and deterministic.

---

## 3. Goals and Non-Goals

### 3.1 Goals

1. Build tab-based transformation pipelines with immediate preview.
2. Materialize outputs as managed datasets (Iceberg).
3. Support scheduled and dependency-aware rebuilds.
4. Provide operational visibility (builds, timings, lineage, healthchecks, notifications).
5. Keep backend/frontend contracts strongly typed and aligned.
6. Execute lazyframe cross-tab dependencies within a single engine run, forwarding LazyFrames between tabs without intermediate datasource reloads.

---

## 4. Users and Primary Use Cases

### 4.1 Personas

- **Analyst/Operator:** Creates analyses, previews results, schedules outputs.
- **Data Engineer:** Maintains reusable logic, validates runs, monitors data quality.
- **Admin:** Configures app-level notifications/settings and runtime behavior.

### 4.2 Core Use Case

1. Create analysis tabs from datasources and build step pipelines.
2. Continue on another tab's logic inside the same analysis.
3. Export tab output to Iceberg and consume it downstream in the same or another analysis.
4. Schedule recurring or dependency-driven builds.
5. Investigate failures/performance via Builds + Lineage + Healthchecks.

---

## 5. Scope (Functional Requirements)

### FR-1 Analyses (Gallery)

- List/search/sort analyses.
- Create/delete analyses.
- Open analysis editor.

### FR-2 Analysis Editor

- Multi-tab editor with visual pipeline canvas.
- Editing lock required for write operations.
- Step operations: add, insert, move, delete, configure.
- Version history: restore and rename versions.
- Save persists tabs and pipeline definition.
- **Unified DAG Execution**: Tabs are frontend-only visualization and grouping, not execution boundaries. Backend treats analysis as a single transform file, resolving all tabs in one request using the full pipeline payload. Input datasources resolve to LazyFrames immediately when in the same DAG; no intermediate datasource reloads.

### FR-3 Datasources

- List/select/search datasources.
- Toggle hidden datasource visibility (only applicable to analysis exports).
- Preview data and schema.
- Download datasource outputs (CSV/Parquet/JSON).
- Iceberg time-travel snapshot selection.
- Configure healthchecks and datasource-level settings.
- Show provenance: whether datasource is raw (imported) or created by analysis.
- For analysis-created datasources, provide direct link to the owning analysis.
- A datasource can be output by exactly one analysis tab, but input by many.
- **Creation Strategies**:
  - **Upload File**: Upload files to namespace-specific upload directory, transform to Iceberg in clean directory. Supports CSV (with delimiter selection) and Excel (with preflight sheet detection). Uploads are re-ingestable; CSV/Excel settings in datasource config trigger re-ingest.
  - **Use Existing Datasource**: Register existing Iceberg datasources by root UUID path; auto-scan branches.
  - **Connect to External Database**: Ingest from external sources into local Iceberg copies with time-travel capabilities. Store connection details for future updates. Supports manual or scheduled ingestion.
- **UI Requirements**:
  - File upload offers only file upload (no path browsing).
  - Excel preflight works reliably for uploads without preselected sheet.
  - Bulk upload enforces single file type per batch; CSV/Excel settings apply globally.
  - Iceberg datasource addition accepts only root UUID path (no branch input); auto-scan branches.
  - Analysis/namespace picker anchored under button (popover-style), not centered modal.
  - Branch picker buttons wider with long branch name support; dropdown appears above table headers.
  - Build logs include datasource create/update events for uploads, database ingest/refresh, and Iceberg registration.
  - Output node hidden toggle visible and first row (hidden/branch/table/build) is compact.
  - Datasources default to master branch but allow selecting other branches even if latest build differs.

### FR-4 Builds and Observability

- View build/preview run history.
- Filter by kind/status/date/search.
- Expand run details (request/result/query plan/step timings).
- Compare two runs (row/schema/timing diffs).
- Mark schedule-triggered runs.

### FR-5 Scheduling (Dataset-Centric)

- CRUD schedules targeting **output datasets** (not analyses).
- **Target**: A datasource with `created_by='analysis'` — the dataset to rebuild.
- **Trigger Types**:
  - **Cron**: Time-based execution (e.g., daily at 9 AM).
  - **Depends On**: Wait for another schedule to complete successfully.
  - **Event**: Trigger when a specific datasource is updated by another build.
- **Provenance Resolution**: System resolves `datasource → analysis → tab` at execution time using the **latest analysis version**.
- **Reusable UI**: Schedule controls in output node, datasource config panel, lineage panel, and dedicated schedules page.
- **Enforcement**: Schedules can only target analysis outputs (`created_by='analysis'`); raw/imported datasources cannot be scheduled.
- **Dependency Ordering**: Scheduler respects both lazyframe (intra-analysis) and exported (inter-analysis) dependencies.

### FR-6 Lineage

- Render datasource and analysis graph.
- Show dependency edges (`uses`, `derived`).
- Open datasource panel with embedded schedule controls.

### FR-7 UDF Library

- Create/manage reusable UDF definitions.
- UDFs available in transformation expressions.

### FR-8 Settings and Notifications

- Global settings popup for runtime-configurable defaults.
- SMTP/Telegram configuration persisted in DB.
- Telegram bot lifecycle managed by app.
- Output notifications and per-step notification pathways.

---

## 6. Data and Behavior Contracts

### 6.1 Analysis Model

- Tabs are stored in `Analysis.pipeline_definition.tabs`.
- Each tab owns `datasource_id`, `datasource_config`, `steps`.

### 6.2 Input vs Output Dataset Contract

- `datasource_id` = tab input source.
- `output_datasource_id` = tab export target dataset.
- Each buildable output is materialized as Iceberg.

### 6.3 Dependency Contract

- **Lazyframe (Intra-Analysis)**: Tab B uses Tab A's output directly within the same analysis via lazyframe passthrough. Building Tab A updates the data for Tab B within the same execution.
- **Exported (Inter-Analysis)**: Tab B uses Tab A's exported output as a datasource. Creates snapshot isolation between analyses.
- **Scheduling Context**: When a schedule targets a dataset, the system builds the producing tab. If other tabs in the same analysis depend on that output (lazyframe), they see the update. Cross-analysis dependencies require separate schedules with `depends_on` or event triggers.

### 6.4 Visibility Contract (`is_hidden`)

- Controls discovery in datasource listing for external analyses.
- Does not disable export existence, snapshots, lineage, schedules, healthchecks, or internal same-analysis usage.
- Toggling `is_hidden` is a metadata-only operation — it must NOT trigger a build or any compute.

### 6.5 View Node Contract

- Inline data preview nodes are pass-through and must not change data semantics downstream.
- Charts are also pass-through but are interactive and pose as filters for downstream nodes.
  - Chart interactions are implemented as metadata on the view node that frontend uses to apply filters on downstream nodes.

### 6.6 Pipeline Canvas Layout Contract

- New analysis creation renders: `DatasourceNode → ConnectionLine → OutputNode` (no empty gaps).
- A default view (preview) step may be added between datasource and output at creation.
- Connection lines between nodes must always be visible — no orphan gaps.

### 6.7 Output Node Layout Contract

The output node has a specific visual structure:

```
Row 1: [Output badge] [table_name label]          ... [is_hidden toggle]
Row 2: [table_name input field]                    ... [Build button]
Row 3: [Build Notification section (collapsible)]
Row 4: [Schedules section (collapsible)]
```

- No namespace field exposed in the output node (namespace is internal config).
- `is_hidden` toggle: small button, always visible, top-right of header. Click toggles the flag via `updateDatasource` — must NOT trigger a build.
- Build button: right side of row 2. Saves analysis first, then calls `buildAnalysisWithPayload()`.

### 6.8 Datasource Provenance Contract

- `created_by` field: `'import'` for raw/uploaded datasources, `'analysis'` for pipeline-built.
- `created_by_analysis_id`: populated for analysis-built datasources, references the analysis that owns the output.
- `output_of_tab_id`: stored in datasource config, references the specific tab that produces this output.
- `source_type` reflects actual data format (`iceberg`, `csv`, `parquet`, etc.), NOT the origin.
- Frontend must display provenance indicator and link to the owning analysis when `created_by='analysis'`.

### 6.9 Scheduling Contract (Dataset-Centric)

**Core Principle**: Schedules target **datasets**, not analyses. The analysis is resolved at execution time from the datasource's provenance.

**Schedule Model**:

- `datasource_id` (required): The target dataset to rebuild.
- `cron_expression`: When to run (time-based trigger).
- `depends_on`: Wait for another schedule to complete (dependency trigger).
- `trigger_on_datasource_id`: Run when another datasource updates (event trigger).
- `analysis_id` is **NOT stored** — resolved from `datasource.created_by_analysis_id` at execution.

**Execution Flow**:

```
Schedule triggers
    ↓
Resolve datasource → created_by_analysis_id, output_of_tab_id
    ↓
Fetch LATEST analysis version
    ↓
Find tab by output_of_tab_id
    ↓
Build that tab (with lazyframe deps auto-resolved)
```

**Benefits**:

- Always uses latest analysis recipe (no version lock-in).
- User thinks: "Rebuild the sales report" not "Run analysis v3".
- Moving output to new analysis automatically updates schedule target.

**Triggers**:

1. **Cron**: Time-based scheduling (e.g., `0 9 * * *` = daily at 9 AM).
2. **Depends On**: DAG-style dependencies between schedules.
3. **Event**: React to upstream dataset updates (datasource change detection via engine runs).

### 6.10 Namespace and Branch Architecture

**Namespace System**:
- Single `DATA_DIR` environment variable replaces multiple data directories.
- Directories automatically derived: `${DATA_DIR}/${NAMESPACE}/uploads`, `${DATA_DIR}/${NAMESPACE}/clean`, `${DATA_DIR}/${NAMESPACE}/exports`.
- Namespace selector in top-left corner (replaces polars/analysis indicator).
- Changing namespace switches all data operations to that namespace's directories.

**Storage Layout**:
- `DATA_DIR/app.db`: Main database for global settings (SMTP, Telegram, app config).
- `DATA_DIR/namespaces/{namespace}/namespace.db`: Per-namespace database for data records:
  - Datasources
  - Analyses
  - Schedules
  - Builds/Engine Runs
  - Healthchecks

**Branch Awareness**:
- Each datasource and analysis output has an associated branch.
- Branch picker allows selecting target branch (e.g., master, dev) per datasource input.
- Lineage view filtered by output datasource + branch; shows upstream inputs including branch overrides.
- Schedules always run on the master branch.
- New uploads always create master branch data.

**Frontend/Backend Contracts**:
- All API endpoints namespace-aware via header or path parameter.
- All UI components reflect current namespace context.
- Branch selection persisted per datasource configuration in analysis pipeline.

---

## 7. End-to-End Flows

### 7.1 Edit and Save

1. Open analysis page.
2. Engine status/defaults initialized.
3. Acquire lock, edit tabs/steps.
4. Save via `PUT /analysis/{id}` with lock payload.
5. Backend persists analysis + version updates.

### 7.2 Preview

1. Frontend sends `POST /compute/preview`.
2. Backend runs partial pipeline up to target step in subprocess.
3. Returns rows/schema/page metadata.
4. Run logged as preview.

### 7.3 Build/Export

1. Manual or scheduler-triggered build starts.
2. Backend exports eligible tab output to datasource destination.
3. Iceberg table written/updated and datasource metadata upserted.
4. Run records + optional healthchecks + notifications produced.

### 7.4 Scheduling (Dataset-Centric Flow)

1. **User creates schedule**:
   - Selects target dataset (must be analysis output).
   - System shows provenance: "Produced by: Analysis X → Tab Y".
   - User configures trigger (cron/depends/event).

2. **Background scheduler loop**:
   - Resolves due schedules (cron expressions + event triggers).
   - Applies dependency ordering (`depends_on` DAG).

3. **Schedule execution**:
   - Resolve `datasource_id` → `created_by_analysis_id` + `output_of_tab_id`.
   - Fetch **latest** analysis version.
   - Find specific tab by `output_of_tab_id`.
   - Build tab with all lazyframe dependencies.
   - Record run state with `triggered_by='schedule'`.

4. **Only output datasets** (`created_by='analysis'`) can be schedule targets.

### 7.5 Lineage

1. Frontend requests lineage endpoint.
2. Backend returns graph nodes/edges from datasource + analysis relationships.

### 7.6 Namespace-Aware Data Handling

1. **Environment Configuration**:
   - Set `DATA_DIR` to base directory (e.g., `/home/kripso/workspace/polars-fastapi-svelte/data`).
   - Set `DEFAULT_NAMESPACE` (e.g., `default`).
   - System derives upload/clean/export paths automatically.

2. **Namespace Selection**:
   - User selects namespace from top-left corner dropdown.
   - All subsequent operations (datasource, analysis, build, schedule) use selected namespace.
   - UI reflects namespace context in all components.

3. **Datasource Creation Flows**:
   - **Upload**: File → Upload dir → Transform to Iceberg in `clean/{uuid}/master` → Register datasource.
   - **Existing**: Path validation → Verify structure `clean/{uuid}/{branches}` → Register datasource.
   - **External**: Connect → Ingest to Iceberg → Store connection details → Register datasource with local path.

4. **Branch Operations**:
   - Select branch per datasource in analysis pipeline.
   - Lineage filters by output datasource + branch.
   - Build exports to specified branch (schedules target master).

---

## 8. Non-Functional Requirements

1. **Type Safety:** Pydantic + TypeScript contract parity.
2. **Isolation:** Compute in engine subprocesses.
3. **Reliability:** Scheduler and bot lifecycle managed in app lifespan.
4. **Observability:** All runs logged with status/timings/error context.
5. **Consistency:** SQLite datetime handling uses naive UTC normalization.
6. **Namespace Awareness:** All components (frontend/backend) must be namespace-aware; data isolation via per-namespace databases and directories.
7. **Branch Awareness:** Datasources, analyses, and lineage must support branch selection and filtering.

---

## 9. Success Metrics

1. Pipeline save/build success rate.
2. Scheduled run completion rate.
3. Mean time to investigate failed run (Builds page workflows).
4. Time-to-first-preview for new analysis.

---

## 10. Risks and Open Product Items

1. Chart interactivity backlog (tooltips/filter/zoom).

---

## 11. Release/Done Criteria

A requirement is complete only when:

1. Behavior matches this PRD in the owning UI area.
2. Backend and frontend types/contracts are aligned.
3. Execution is visible in runs/lineage/snapshots where relevant.
4. `just verify` passes with zero errors and zero warnings.
