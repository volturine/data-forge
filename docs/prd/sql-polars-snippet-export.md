# PRD: SQL & Polars Snippet Export
 
## Overview
 
Allow users to export any analysis pipeline (or individual tab/step) as a standalone SQL query or Polars Python script. This gives users a portable, reproducible version of their visual pipeline that can run outside Data-Forge.
 
## Problem Statement
 
Data-Forge pipelines are defined as visual DAGs of operations (filter, join, group, etc.) stored as JSON. Users who want to:
 
- Share logic with colleagues who don't use Data-Forge
- Run transformations in a CI/CD pipeline or Jupyter notebook
- Audit the exact computation performed
- Migrate away from Data-Forge
 
...have no way to extract the pipeline as executable code. They must manually reconstruct the logic by reading each step's configuration.
 
### Current State
 
| Capability | Status |
|-----------|--------|
| Visual pipeline builder | ✅ Full DAG editor |
| Pipeline stored as JSON | ✅ `pipeline_definition` on Analysis |
| Polars execution engine | ✅ Steps compiled to Polars LazyFrame ops |
| SQL execution | ✅ Some steps use SQL under the hood |
| Export as code | ❌ Not available |
| Export as SQL | ❌ Not available |
 
## Goals
 
| # | Goal | Success Metric |
|---|------|----------------|
| G-1 | Export pipeline as Polars Python script | Generated script runs standalone with `pip install polars` |
| G-2 | Export pipeline as SQL query | Generated SQL is valid for PostgreSQL/DuckDB |
| G-3 | Per-tab and per-step granularity | Users can export the full pipeline, a single tab, or a single step chain |
| G-4 | Copy to clipboard | One-click copy of generated code |
| G-5 | Readable output | Generated code uses meaningful variable names and comments |
 
## Non-Goals
 
- Bi-directional sync (editing exported code and importing it back)
- Pandas export (Polars only)
- Spark/PySpark export
- Export as dbt model (future consideration)
- Exporting UDF implementations (referenced by name only)
 
## User Stories
 
### US-1: Export Full Pipeline as Polars Script
 
> As a data analyst, I want to export my entire analysis pipeline as a Python script using Polars.
 
**Acceptance Criteria:**
 
1. "Export" button available in the analysis editor toolbar.
2. Clicking opens a modal with two tabs: "Polars (Python)" and "SQL".
3. Polars tab shows a complete Python script:
   - Imports (`import polars as pl`)
   - Data loading (`pl.scan_parquet("path")` or `pl.scan_csv("path")` per datasource)
   - Each step as a chained Polars operation with a comment naming the step
   - Final `.collect()` call
4. Datasource paths use placeholder variables with instructions to replace them.
5. Script is syntactically valid Python.
 
### US-2: Export Pipeline as SQL
 
> As a data engineer, I want to export my pipeline as a SQL query for use in our data warehouse.
 
**Acceptance Criteria:**
 
1. SQL tab in the export modal shows a single SQL query (or CTE chain).
2. Each step that has a SQL equivalent is rendered as a CTE.
3. Steps without direct SQL equivalents (e.g., custom UDFs, Polars-specific operations) include a comment explaining the limitation and the original step config.
4. Table references use placeholder names matching datasource names.
5. SQL dialect is PostgreSQL-compatible with DuckDB compatibility notes where applicable.
 
### US-3: Export Single Tab
 
> As a user, I want to export just one tab of my multi-tab analysis.
 
**Acceptance Criteria:**
 
1. Right-click on a tab → "Export as Code".
2. Export modal shows code for that tab only.
3. Upstream dependencies (datasource inputs) are included as data loading statements.
 
### US-4: Copy and Download
 
> As a user, I want to quickly copy the generated code or download it as a file.
 
**Acceptance Criteria:**
 
1. "Copy to Clipboard" button at the top of the code view.
2. "Download" button saves as `.py` (Polars) or `.sql` (SQL).
3. Filename defaults to `{analysis_name}_{tab_name}.py` or `.sql`.
4. Syntax highlighting in the modal (Python and SQL).
 
## Technical Design
 
### Backend: Code Generation Service
 
New module: `backend/modules/export/`
 
**Polars Code Generator:**
 
```python
class PolarsCodeGenerator:
    def generate(self, pipeline: PipelineDefinition, tab_id: str | None = None) -> str:
        """Convert pipeline steps to a Polars Python script."""
```
 
Maps each step type to its Polars code equivalent:
 
| Step Type | Polars Code |
|-----------|-------------|
| Filter | `.filter(pl.col("x") > 10)` |
| Select | `.select(["col1", "col2"])` |
| Rename | `.rename({"old": "new"})` |
| Group By | `.group_by("col").agg(pl.col("val").sum())` |
| Sort | `.sort("col", descending=True)` |
| Join | `df1.join(df2, on="key", how="left")` |
| Cast | `.with_columns(pl.col("x").cast(pl.Int64))` |
| Formula | `.with_columns((pl.col("a") + pl.col("b")).alias("c"))` |
| Pivot | `.pivot(on="col", values="val", aggregate_function="sum")` |
| Unpivot | `.unpivot(on=["a", "b"], variable_name="key", value_name="val")` |
| Deduplicate | `.unique(subset=["col"])` |
| Sample | `.sample(n=100)` |
| AI Transform | `# AI step: requires external LLM call (not exportable as pure Polars)` |
 
**SQL Code Generator:**
 
```python
class SqlCodeGenerator:
    def generate(self, pipeline: PipelineDefinition, tab_id: str | None = None) -> str:
        """Convert pipeline steps to a SQL CTE chain."""
```
 
Maps step types to SQL:
 
| Step Type | SQL |
|-----------|-----|
| Filter | `WHERE x > 10` |
| Select | `SELECT col1, col2` |
| Group By | `GROUP BY col` with aggregation |
| Sort | `ORDER BY col DESC` |
| Join | `LEFT JOIN t2 ON t1.key = t2.key` |
| Formula | `SELECT *, (a + b) AS c` |
| Pivot | `CROSSTAB` or conditional aggregation |
 
### API Endpoint
 
```
POST /api/v1/export/code
Body: { analysis_id, tab_id?, format: "polars" | "sql" }
Response: { code: string, warnings: string[] }
```
 
`warnings` lists any steps that couldn't be fully translated (UDFs, AI steps, etc.).
 
### Frontend: Export Modal
 
- Trigger: toolbar "Export" button or tab context menu.
- Modal with code viewer (syntax-highlighted using a lightweight library like `shiki` or `highlight.js`).
- Toggle between Polars and SQL.
- Copy and Download buttons.
- Warning banner if some steps have limited translation.
 
## Risks
 
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Complex step configs produce incorrect code | Medium | High | Unit tests per step type; "preview" mode that runs generated code and compares output |
| SQL translation gaps | High | Medium | Clearly mark untranslatable steps; don't silently skip them |
| Polars API changes break generated code | Low | Medium | Pin to Polars version in generated script header comment |
 
## Acceptance Criteria
 
- [ ] Export modal accessible from analysis editor toolbar
- [ ] Polars export produces a runnable Python script for a pipeline with filter, join, group_by, and sort steps
- [ ] SQL export produces valid PostgreSQL-compatible SQL for the same pipeline
- [ ] Per-tab export works correctly
- [ ] Untranslatable steps produce clear comments/warnings
- [ ] Copy to clipboard works
- [ ] Download produces correctly named files
- [ ] Syntax highlighting in the modal
- [ ] `just verify` passes