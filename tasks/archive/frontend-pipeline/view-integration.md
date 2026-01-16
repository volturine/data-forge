# Frontend: Pipeline View Integration

**Priority:** HIGH  
**Status:** ✅ Complete  
**Depends On:** frontend-viewers/inline-table.md ✅  
**Blocks:** frontend-editor/remove-run-button.md

---

## Goal

Integrate InlineDataTable into the pipeline canvas, showing it for "view" step types and passing the required props (datasourceId, pipeline, stepId).

---

## Changes Required

### 1. Update StepNode Component

**File:** `frontend/src/lib/components/pipeline/StepNode.svelte`

Add InlineDataTable rendering for view steps:

```svelte
<script lang="ts">
  import { InlineDataTable } from '$lib/components/viewers'
  
  interface Props {
    step: PipelineStep
    datasourceId?: string // NEW
    allSteps?: PipelineStep[] // NEW
    // ... existing props
  }
  
  let { step, datasourceId, allSteps = [], ...rest }: Props = $props()
</script>

<!-- After step header and config -->
{#if step.type === 'view' && datasourceId && allSteps.length > 0}
  <div class="view-preview">
    <InlineDataTable 
      datasourceId={datasourceId}
      pipeline={allSteps}
      stepId={step.id}
      rowLimit={1000}
    />
  </div>
{/if}
```

### 2. Update PipelineCanvas Component

**File:** `frontend/src/lib/components/pipeline/PipelineCanvas.svelte`

Pass datasourceId and full pipeline to StepNode:

```svelte
<script lang="ts">
  interface Props {
    datasourceId?: string // NEW
    // ... existing props
  }
  
  let { datasourceId, steps, ...rest }: Props = $props()
</script>

<!-- In the step rendering loop -->
{#each steps as step (step.id)}
  <StepNode 
    {step}
    datasourceId={datasourceId} 
    allSteps={steps}
    <!-- ... existing props -->
  />
{/each}
```

### 3. Update Analysis Page

**File:** `frontend/src/routes/analysis/[id]/+page.svelte`

Extract datasource ID from analysis and pass to PipelineCanvas:

```svelte
<script lang="ts">
  // ... existing code ...
  
  const datasourceId = $derived(
    analysis?.pipeline_definition?.datasource_ids?.[0] ?? undefined
  )
</script>

<PipelineCanvas 
  datasourceId={datasourceId}
  steps={pipeline.steps}
  <!-- ... existing props -->
/>
```

---

## File Locations

- `frontend/src/lib/components/pipeline/StepNode.svelte`
- `frontend/src/lib/components/pipeline/PipelineCanvas.svelte`
- `frontend/src/routes/analysis/[id]/+page.svelte`

---

## Testing

### Integration Test

1. **Start servers:**
   ```bash
   # Terminal 1
   cd backend && uv run main.py
   
   # Terminal 2
   cd frontend && npm run dev
   ```

2. **Create test scenario:**
   - Open existing analysis or create new one
   - Upload CSV datasource
   - Add a Select step (select 2-3 columns)
   - Add a View step below it
   - **Expected:** View step should immediately show selected columns inline

3. **Test auto-refresh:**
   - Change the Select step config (add/remove column)
   - **Expected:** View step auto-refreshes with new columns

4. **Test multiple views:**
   - Add Filter step
   - Add another View step
   - **Expected:** Both views show data from their respective positions

5. **Test pagination:**
   - Use datasource with 1000+ rows
   - Add View step
   - **Expected:** Pagination controls appear, can navigate pages

---

## Status

- [x] Update StepNode to show InlineDataTable for view steps
- [x] Update PipelineCanvas to pass datasourceId and allSteps
- [x] Update analysis page to extract and pass datasourceId
- [x] TypeScript check passes (0 errors)
- [ ] Test inline view rendering (pending manual test)
- [ ] Test auto-refresh on upstream changes (pending manual test)
- [ ] Test multiple views (pending manual test)
- [ ] Test pagination (pending manual test)

---

## Implementation Summary

### Files Modified

1. **StepNode.svelte**
   - Added `datasourceId` and `allSteps` props
   - Import `InlineDataTable` component
   - Conditional rendering: shows InlineDataTable when `step.type === 'view'`
   - Added `.view-preview` CSS class for styling

2. **PipelineCanvas.svelte**
   - Added `datasourceId` prop
   - Pass `datasourceId` and `allSteps={steps}` to each StepNode

3. **analysis/[id]/+page.svelte**
   - Added `datasourceId` derived value from `analysisQuery.data`
   - Extracts first datasource ID from `pipeline_definition.datasource_ids`
   - Pass `datasourceId` to PipelineCanvas component

### How It Works

```
Analysis Page
  ↓ extracts datasourceId from analysis.pipeline_definition
PipelineCanvas
  ↓ passes datasourceId + full steps array
StepNode
  ↓ if step.type === 'view'
InlineDataTable
  ↓ uses TanStack Query with queryKey: [datasourceId, stepId, pipeline]
Backend /api/v1/compute/preview
  ↓ executes lazy pipeline up to target step
Returns paginated data
```

### Auto-Refresh Mechanism

When any step in the pipeline changes:
1. The `steps` array reference changes in PipelineCanvas
2. StepNode receives new `allSteps` prop value
3. InlineDataTable's `pipeline` prop updates
4. TanStack Query detects `queryKey` change (includes full pipeline)
5. Query automatically re-fetches preview data

No manual refresh needed!

---

## Design Notes

### Why Pass Full Pipeline?

The `allSteps` array is passed to compute the view at the correct position. The backend needs all steps up to the target view to execute the pipeline correctly.

### Datasource ID Extraction

The datasource ID comes from `analysis.pipeline_definition.datasource_ids[0]`. Currently only single-datasource pipelines are supported.

### View Step Positioning

InlineDataTable renders inside the StepNode component, appearing below the step header/config. This keeps the data preview visually connected to its step.

### Performance Considerations

- TanStack Query caches results for 30 seconds
- Only view steps trigger preview queries
- Queries are disabled if datasourceId or stepId is missing
- Auto-refresh only happens when pipeline reference changes (not on every render)
