# PRD: New Analysis Creation Flow

## Overview

Redesign the analysis creation flow to be more guided, informative, and capable. Replace the current 3-step wizard (name → select datasources → review) with a richer flow that supports template selection, AI-assisted pipeline generation, multi-datasource configuration with branch/snapshot selection, and a meaningful review step with pipeline preview.

## Problem Statement

The current analysis creation flow (`/routes/analysis/new/+page.svelte`) is a 3-step wizard:

1. **Step 1 — Details**: Enter name and optional description.
2. **Step 2 — Select Data Sources**: Multi-select from existing datasources.
3. **Step 3 — Review & Create**: See summary and confirm.

This flow has several limitations:

1. **No template support**: Every analysis starts blank — users cannot start from a template (e.g., "ELT pattern", "time-series analysis", "data quality audit").
2. **No AI-assisted setup**: Users must manually configure every step after creation — the AI chat is only available inside the editor.
3. **Limited datasource configuration**: No branch or snapshot selection at creation time — defaults to `master` branch.
4. **No output configuration**: Output datasource naming and Iceberg table configuration deferred to the editor.
5. **Thin review step**: Review only shows name and selected datasources — no pipeline preview, no validation.
6. **No import/clone**: Cannot create an analysis by cloning an existing one or importing a pipeline definition.

### Current Implementation

```
Step 1: Details          Step 2: Datasources      Step 3: Review
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ Name: [________] │    │ ☑ customers.csv  │    │ Name: Sales ETL  │
│ Desc: [________] │    │ ☑ products.parq  │    │ Sources: 2       │
│                  │    │ ☐ orders.json    │    │                  │
│      [Next →]    │    │ ☐ regions.csv    │    │     [Create]     │
└──────────────────┘    └──────────────────┘    └──────────────────┘
```

## Goals

| # | Goal | Success Metric |
|---|------|----------------|
| G-1 | Faster time-to-first-pipeline | Users go from creation to a runnable pipeline 50% faster |
| G-2 | Template-based quick start | 5+ built-in templates, each producing a valid pipeline skeleton |
| G-3 | AI-assisted creation | Users can describe intent in natural language at creation time |
| G-4 | Full datasource configuration at creation | Branch and snapshot selection available before pipeline editing |
| G-5 | Meaningful review with preview | Review shows pipeline diagram, estimated complexity, and validation |
| G-6 | Clone and import capabilities | Users can duplicate existing analyses or import JSON definitions |

## Non-Goals

- Collaborative analysis creation (multi-user simultaneous editing)
- Versioned templates (template marketplace)
- Automated datasource recommendation (suggest datasources based on analysis name)
- Creation from external tools (API-only creation is already supported)

## User Stories

### US-1: Create Analysis from Template

> As a user, I want to select a pipeline template to start with a pre-configured set of steps instead of a blank canvas.

**Acceptance Criteria:**

1. Creation flow shows template selection as an optional first step.
2. Built-in templates:
   - **Blank** — empty pipeline (current default).
   - **Data Quality Audit** — filter nulls, count missing, summary stats.
   - **ELT Transform** — filter → select → rename → export.
   - **Aggregation Report** — group_by → aggregate → sort → export.
   - **Time-Series Analysis** — time column detection → resample → fill gaps → plot.
   - **Join & Enrich** — multi-source join → with_columns → export.
3. Template preview shows: step diagram, description, required input columns.
4. Selecting a template pre-populates the pipeline with steps (configurable in editor).
5. Templates are JSON definitions stored as static assets.

### US-2: AI-Assisted Analysis Creation

> As a user, I want to describe what I want to build in plain language and have the AI generate a pipeline skeleton.

**Acceptance Criteria:**

1. "Describe your analysis" text area in the creation flow.
2. AI generates a pipeline definition based on:
   - User's description.
   - Selected datasource schema (columns, types).
   - Available operations catalog.
3. Generated pipeline shown as a preview before creation.
4. User can edit, accept, or regenerate.
5. AI generation uses the configured chat provider (see AI Chat API PRD).

### US-3: Advanced Datasource Configuration at Creation

> As a user, I want to select specific branches and snapshots for my input datasources during creation, not just after.

**Acceptance Criteria:**

1. Datasource selection step shows expandable config per datasource.
2. Per-datasource options:
   - Branch selector (list of branches for Iceberg datasources).
   - Snapshot selector (optional, defaults to latest).
   - Schema preview (columns and types).
   - Row count and size info.
3. Multi-datasource with tab mapping: assign datasources to tabs.
4. Drag to reorder datasources (tab order).

### US-4: Output Configuration at Creation

> As a user, I want to configure output datasource naming and format during creation.

**Acceptance Criteria:**

1. Output configuration step after datasource selection.
2. Per-tab output config:
   - Output name (auto-generated from analysis name + tab index, editable).
   - Iceberg namespace (default from settings).
   - Iceberg table name (auto-generated, editable).
   - Build mode selector: full / incremental / recreate.
3. Validation: unique output names, valid table names.

### US-5: Pipeline Preview in Review Step

> As a user, I want to see a visual preview of my pipeline before creating it.

**Acceptance Criteria:**

1. Review step shows a visual pipeline diagram (miniature version of PipelineCanvas).
2. For template-based creation: shows template steps with datasource mappings.
3. For AI-generated creation: shows generated steps.
4. For blank creation: shows datasource nodes and empty output nodes.
5. Validation results shown: warnings about missing configs, schema mismatches.
6. Estimated complexity indicator (step count, expected output size category).

### US-6: Clone Existing Analysis

> As a user, I want to create a new analysis by cloning an existing one.

**Acceptance Criteria:**

1. "Clone" action on analysis cards in the gallery.
2. Clone dialog: new name (pre-filled as "Copy of {original}"), description.
3. Clone creates a new analysis with identical pipeline definition.
4. Clone creates new output result_ids (not reusing the original's output datasources).
5. Redirects to editor with the cloned analysis.

### US-7: Import Pipeline Definition

> As a user, I want to import a pipeline definition from a JSON file.

**Acceptance Criteria:**

1. "Import" option in the creation flow.
2. Accepts JSON file matching the analysis pipeline schema.
3. Validates the imported definition before creation.
4. Maps datasource references: if imported datasource IDs don't exist, prompts user to remap.
5. Creates new output result_ids (import doesn't reuse original outputs).

## Technical Design

### Backend

#### New/Updated Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/analysis/templates` | List available templates |
| `GET` | `/api/v1/analysis/templates/{template_id}` | Get template definition |
| `POST` | `/api/v1/analysis/generate` | AI-generate pipeline from description |
| `POST` | `/api/v1/analysis/clone/{analysis_id}` | Clone an existing analysis |
| `POST` | `/api/v1/analysis/import` | Import pipeline from JSON |
| `POST` | `/api/v1/analysis/validate` | Validate pipeline definition (existing, enhanced) |

#### Template System

```python
# backend/modules/analysis/templates.py

BUILTIN_TEMPLATES = {
    "blank": AnalysisTemplate(
        id="blank",
        name="Blank Analysis",
        description="Start with an empty pipeline.",
        icon="file",
        steps=[],
    ),
    "data_quality": AnalysisTemplate(
        id="data_quality",
        name="Data Quality Audit",
        description="Assess data quality: null counts, type validation, summary statistics.",
        icon="shield-check",
        steps=[
            TemplateStep(type="view", config={}),
            TemplateStep(type="filter", config={"description": "Filter rows with nulls"}),
            TemplateStep(type="with_columns", config={"description": "Add quality flags"}),
            TemplateStep(type="groupby", config={"description": "Aggregate quality metrics"}),
        ],
    ),
    "elt_transform": AnalysisTemplate(
        id="elt_transform",
        name="ELT Transform",
        description="Extract, load, and transform data into a clean output.",
        icon="arrow-right-left",
        steps=[
            TemplateStep(type="filter", config={"description": "Filter input data"}),
            TemplateStep(type="select", config={"description": "Select relevant columns"}),
            TemplateStep(type="rename", config={"description": "Rename to target schema"}),
            TemplateStep(type="export", config={"description": "Export to Iceberg table"}),
        ],
    ),
    # ... more templates
}
```

#### AI Pipeline Generation

```python
# backend/modules/analysis/generator.py

async def generate_pipeline(
    description: str,
    datasource_schemas: list[DataSourceSchema],
    provider: AIProvider,
    model: str,
) -> GeneratedPipeline:
    """Use AI to generate a pipeline definition from a natural language description."""
    system_prompt = build_generation_prompt(
        operation_catalog=get_operation_catalog(),
        datasource_schemas=datasource_schemas,
    )

    response = await provider.chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": description},
        ],
        model=model,
        temperature=0.3,  # Lower temperature for structured output
    )

    # Parse and validate the generated pipeline
    pipeline = parse_pipeline_response(response.content)
    validation = validate_pipeline(pipeline, datasource_schemas)

    return GeneratedPipeline(
        pipeline=pipeline,
        validation=validation,
        explanation=response.content,
    )
```

#### Clone Implementation

```python
# backend/modules/analysis/service.py

async def clone_analysis(
    session: AsyncSession,
    analysis_id: str,
    new_name: str,
    new_description: str | None = None,
) -> Analysis:
    """Create a deep clone of an analysis with new output IDs."""
    original = await get_analysis(session, analysis_id)

    # Deep copy pipeline definition
    pipeline = deepcopy(original.pipeline_definition)

    # Generate new result_ids for all tabs
    for tab in pipeline.get("tabs", []):
        if "output" in tab:
            tab["output"]["result_id"] = str(uuid4())

    # Create new analysis
    new_analysis = Analysis(
        name=new_name,
        description=new_description or original.description,
        pipeline_definition=pipeline,
    )
    session.add(new_analysis)
    await session.flush()

    # Copy datasource associations
    for assoc in original.datasource_associations:
        new_assoc = AnalysisDataSource(
            analysis_id=new_analysis.id,
            datasource_id=assoc.datasource_id,
        )
        session.add(new_assoc)

    await session.commit()
    return new_analysis
```

### Frontend

#### Revised Creation Flow

Replace the 3-step wizard with a 5-step flow:

```
Step 1: Start          Step 2: Data           Step 3: Design
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ How do you want  │  │ Select Sources   │  │ Choose Template  │
│ to start?        │  │                  │  │                  │
│                  │  │ ☑ customers.csv  │  │ [Blank]          │
│ ○ New (template) │  │   branch: main ▾ │  │ [Data Quality]   │
│ ○ New (AI)       │  │   snap: latest ▾ │  │ [ELT Transform]  │
│ ○ Clone existing │  │                  │  │ [Aggregation]    │
│ ○ Import JSON    │  │ ☑ products.parq  │  │ [Time-Series]    │
│                  │  │   branch: main ▾ │  │                  │
│ Name: [________] │  │                  │  │ — OR —           │
│ Desc: [________] │  │                  │  │ 💬 Describe:     │
│                  │  │                  │  │ [______________] │
│      [Next →]    │  │      [Next →]    │  │ [Generate ✨]    │
└──────────────────┘  └──────────────────┘  └──────────────────┘

Step 4: Output         Step 5: Review
┌──────────────────┐  ┌──────────────────────────────┐
│ Configure Output │  │ Review & Create              │
│                  │  │                              │
│ Tab 1:           │  │ Name: Sales ETL              │
│  Name: sales_out │  │ Sources: 2                   │
│  Table: sales    │  │ Template: ELT Transform      │
│  Mode: full ▾    │  │ Steps: 4                     │
│                  │  │                              │
│ Tab 2:           │  │ [ds] → [filter] → [select]  │
│  Name: prod_out  │  │        → [rename] → [export] │
│  Table: products │  │                              │
│  Mode: full ▾    │  │ ✓ Validation passed          │
│                  │  │                              │
│      [Next →]    │  │          [Create Analysis]   │
└──────────────────┘  └──────────────────────────────┘
```

#### Component Structure

```
routes/analysis/new/
├── +page.svelte                         # Main creation page (orchestrator)
components/analysis-creation/
├── CreationWizard.svelte                # Wizard container with step navigation
├── StartStep.svelte                     # Step 1: creation mode + basic info
├── DataSourceStep.svelte                # Step 2: datasource selection + config
├── DesignStep.svelte                    # Step 3: template or AI generation
├── OutputStep.svelte                    # Step 4: output configuration
├── ReviewStep.svelte                    # Step 5: preview and validation
├── TemplateCard.svelte                  # Template selection card
├── TemplatePreview.svelte               # Template step diagram preview
├── AIGeneratorInput.svelte              # AI description input with generate button
├── PipelinePreviewMini.svelte           # Miniature pipeline diagram for review
├── DatasourceConfigRow.svelte           # Per-datasource branch/snapshot config
├── OutputConfigRow.svelte               # Per-tab output configuration
└── CloneAnalysisPicker.svelte           # Analysis picker for clone mode
```

#### Step Navigation

```svelte
<!-- CreationWizard.svelte -->
<script lang="ts">
    type CreationMode = 'template' | 'ai' | 'clone' | 'import';

    let currentStep = $state(1);
    let creationMode = $state<CreationMode>('template');

    // Steps vary by mode
    const steps = $derived.by(() => {
        switch (creationMode) {
            case 'template':
            case 'ai':
                return ['Start', 'Data', 'Design', 'Output', 'Review'];
            case 'clone':
                return ['Start', 'Clone', 'Review'];
            case 'import':
                return ['Start', 'Import', 'Remap', 'Review'];
        }
    });
</script>
```

#### AI Generation Integration

```svelte
<!-- AIGeneratorInput.svelte -->
<script lang="ts">
    let description = $state('');
    let generating = $state(false);
    let generatedPipeline = $state<GeneratedPipeline | null>(null);

    async function generate() {
        generating = true;
        try {
            const result = await api.post('/analysis/generate', {
                description,
                datasource_ids: selectedDatasourceIds,
            });
            generatedPipeline = result;
        } finally {
            generating = false;
        }
    }
</script>

<textarea bind:value={description} placeholder="Describe what you want to build..." />
<button onclick={generate} disabled={generating || !description.trim()}>
    {generating ? 'Generating...' : 'Generate Pipeline ✨'}
</button>

{#if generatedPipeline}
    <PipelinePreviewMini pipeline={generatedPipeline.pipeline} />
    <p>{generatedPipeline.explanation}</p>
    <button onclick={accept}>Use This Pipeline</button>
    <button onclick={generate}>Regenerate</button>
{/if}
```

### Dependencies

No new dependencies required.

### Security Considerations

- AI-generated pipelines are validated server-side before creation (same as manual pipelines).
- Imported JSON validated against the pipeline schema — arbitrary JSON rejected.
- Clone preserves no references to original analysis's output datasources (new result_ids).
- Template definitions are static (not user-editable) — no injection risk.

## Migration

- No database migration — uses existing `Analysis` model and `pipeline_definition` JSON field.
- Existing `POST /api/v1/analysis` endpoint unchanged — new flow constructs the same payload.
- New endpoints (`/templates`, `/generate`, `/clone`, `/import`) are additive.

## Rollout Plan

| Phase | Scope | Duration |
|-------|-------|----------|
| 1 | Backend: Template system and template endpoints | 2 days |
| 2 | Backend: Clone and import endpoints | 2 days |
| 3 | Backend: AI pipeline generation endpoint | 3 days |
| 4 | Frontend: Revised wizard with 5-step flow | 3 days |
| 5 | Frontend: Template selection and preview | 2 days |
| 6 | Frontend: AI generation integration | 2 days |
| 7 | Frontend: Clone picker and import flow | 2 days |
| 8 | Frontend: Pipeline preview mini-diagram | 2 days |
| 9 | Testing: All creation modes, validation, edge cases | 2 days |

## Open Questions

1. Should templates be editable by users (create custom templates from existing analyses)?
2. Should AI generation be streaming (show pipeline building in real time) or batch (generate all at once)?
3. Should the clone flow allow modifying datasource mappings (clone pipeline but with different input datasources)?
4. How do we handle template steps that reference columns that don't exist in the selected datasource?
