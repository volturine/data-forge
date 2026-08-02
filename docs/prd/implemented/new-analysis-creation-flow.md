# PRD: New Analysis Creation Flow

> **Status (audited 2026-08-02): Implemented.**
> **Portfolio:** [PRD index](../README.md)

## Summary

The analysis creation experience is a guided, mode-aware flow at
`/analysis/new`. It supports built-in templates, AI-assisted pipeline drafts,
branch and snapshot selection, output configuration, visual review, analysis
duplication, and JSON import with datasource remapping.

The implementation deliberately uses one route-level Svelte orchestrator
instead of the component split proposed in the original design. The shipped
structure keeps cross-step state, validation, and submission in one place while
reusing shared datasource and UI components.

## Shipped User Experience

The first step offers four creation modes:

1. **Template** — select datasources, choose a static built-in pipeline, configure
   outputs, validate, and create.
2. **AI-assisted** — select datasources, describe the intended analysis, inspect
   or regenerate a batch-generated draft, configure outputs, validate, and
   create.
3. **Clone existing** — choose an analysis, edit the suggested copy name and
   description, review, and duplicate it with independent identities.
4. **Import JSON** — load an analysis pipeline definition, remap missing
   datasource references, review, validate, and create it with independent
   identities.

For template and AI modes, datasource configuration includes source ordering,
Iceberg branch selection, optional snapshot selection, schema metadata, row
count, and size where the datasource exposes them. Output configuration includes
editable output name, Iceberg namespace and table, and full, incremental, or
recreate build mode.

The review step shows the source-to-step-to-output pipeline, source and step
counts, a complexity category, estimated output size, local configuration errors,
and server validation status before creation.

## Built-in Templates

Templates are repository-owned static definitions in
`packages/backend/modules/analysis/builtin_templates.json` and are exposed by
`packages/backend/modules/analysis/templates.py`.

| ID | Display name | Skeleton |
|---|---|---|
| `blank` | Blank | Empty pipeline |
| `data_quality_audit` | Data Quality Audit | View, filter, derived columns, aggregation |
| `elt_transform` | ELT Transform | Filter, select, rename, export |
| `aggregation_report` | Aggregation Report | Aggregate, sort, view, export |
| `time_series_analysis` | Time-Series Analysis | Time operation, gap fill, line plot |
| `join_and_enrich` | Join & Enrich | Join, derived columns, select, export |

Each detail payload includes its description, step preview, and required-input
column guidance. Template steps remain editable in the analysis editor after
creation.

## API Contract

The implemented endpoints are:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/analysis/templates` | List the six built-in templates |
| `GET` | `/api/v1/analysis/templates/{template_id}` | Return a template and its preview metadata |
| `POST` | `/api/v1/analysis/generate` | Generate and validate a pipeline draft with the configured AI provider |
| `POST` | `/api/v1/analysis/import` | Remap, re-identify, validate, and persist an imported pipeline |
| `POST` | `/api/v1/analysis/{analysis_id}/duplicate` | Duplicate an analysis with new tab, step, and output identities |
| `POST` | `/api/v1/analysis/validate` | Validate a complete creation payload without persisting it |

The original proposal named the duplication route
`/api/v1/analysis/clone/{analysis_id}`. That route was not shipped; the canonical
resource-oriented route is `/{analysis_id}/duplicate`.

No database migration was required. All modes ultimately create the existing
analysis model and pipeline-definition shape.

## Resolved Product Decisions

- **Template ownership:** built-in templates remain static, repository-owned
  definitions. User-authored templates and a template marketplace remain out of
  scope.
- **Generation mode:** AI generation is batch-based. The draft is shown before
  creation and can be regenerated; streaming generation is not part of this
  flow.
- **Clone mapping:** duplication preserves external datasource mappings. Use the
  import flow when datasource references need to be remapped.
- **Missing columns:** template column requirements are guidance. Missing or
  incompatible configuration is surfaced in preview and validation and remains
  editable; the system does not silently substitute columns.
- **Identity isolation:** duplication and import generate new tab, step, and
  output result identities. References between derived tabs and steps are
  rewritten to those new identities.
- **Provider safety:** generated JSON is parsed and server-validated against the
  selected datasource IDs and operation schemas before it can be accepted.

## Acceptance Audit

| Capability | Evidence | Result |
|---|---|---|
| Optional template selection and six built-ins | Template API, static catalog, and creation UI | Complete |
| Template description, step diagram, and input guidance | Template detail response and design-step preview | Complete |
| AI prompt, datasource schema context, operation catalog, preview, and regenerate | Generation service and AI creation mode | Complete |
| Branch, snapshot, schema, row-count, size, and source ordering | Datasource configuration step | Complete |
| Output name, Iceberg target, and build mode | Output configuration step | Complete |
| Pipeline diagram, validation, and complexity summary | Review step | Complete |
| Gallery clone action, suggested name, independent outputs, editor redirect | Gallery duplicate modal and duplicate endpoint | Complete |
| JSON validation, datasource remapping, and independent identities | Import mode and import endpoint | Complete |

## Verification

Focused backend coverage in `packages/backend/tests/test_analysis.py` verifies:

- the complete template catalog, template detail metadata, and unknown IDs;
- valid AI generation using a controlled fake provider response;
- malformed AI JSON and unknown datasource or operation references;
- import datasource and join-source remapping;
- duplicate tab, step, and output identity regeneration while preserving the
  external datasource mapping; and
- duplicate reference rewriting for derived-tab `parent_id`, upstream
  `analysis_tab_id` and result ID, and step `depends_on` links.

End-to-end coverage in `packages/frontend/tests/analysis-crud.test.ts` verifies
the blank creation path and a full Data Quality Audit wizard path through editor
navigation. The template scenario selects and reorders two datasources, checks
branch and latest-snapshot controls, edits output name/namespace/table/build
mode, and asserts the review diagram, step count, complexity, output target, and
successful server validation. A separate import scenario uploads JSON with a
missing datasource reference, selects its visible remapping, reviews the remap,
and creates the analysis. Gallery duplication remains covered through its modal
and editor redirect. None of these tests depends on a live AI provider.

The focused backend audit completed with 11 passing tests on 2026-08-02. On the
final revision, `just verify` passed, `just test` passed all 966 backend unit,
94 backend integration, 310 worker, 4 scheduler, and 1,163 frontend tests (with
two intentional integration skips), and five consecutive `just test-e2e` runs
passed all 351 tests with zero retries.

## Out of Scope

- Collaborative creation
- User-authored or versioned templates
- Automated datasource recommendation
- Streaming AI generation
- A template marketplace
- Creation from external tools beyond the existing API

The original time-to-first-pipeline goal requires product analytics over real
usage and is not asserted by this implementation record.
