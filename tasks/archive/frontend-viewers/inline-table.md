# Frontend: Inline Data Table Component

**Priority:** HIGH  
**Status:** ✅ Complete  
**Depends On:** frontend-api/compute-preview.md ✅  
**Blocks:** frontend-pipeline/view-integration.md

---

## Goal

Create a Svelte 5 component that displays paginated data inline within view step nodes using TanStack Query for auto-refresh.

---

## Component Spec

**File:** `frontend/src/lib/components/viewers/InlineDataTable.svelte`

### Props

```typescript
interface Props {
  datasourceId: string
  pipeline: Array<{
    id: string
    type: string
    config: Record<string, unknown>
  }>
  stepId: string
  rowLimit?: number
}
```

### Features

- ✅ Auto-fetch data when step is added
- ✅ Auto-refresh when upstream pipeline changes
- ✅ Pagination (1000 rows default, paginated display)
- ✅ Loading/error states
- ✅ Column headers
- ✅ Responsive table layout

---

## Implementation

```svelte
<script lang="ts">
  import { createQuery } from '@tanstack/svelte-query'
  import { previewStep } from '$lib/api/compute'
  import type { StepPreviewResponse } from '$lib/api/compute'

  interface Props {
    datasourceId: string
    pipeline: Array<{ id: string; type: string; config: Record<string, unknown> }>
    stepId: string
    rowLimit?: number
  }

  let { datasourceId, pipeline, stepId, rowLimit = 1000 }: Props = $props()
  let currentPage = $state(1)

  // Query key includes pipeline to trigger re-fetch on changes
  const query = createQuery({
    queryKey: ['step-preview', datasourceId, stepId, pipeline, currentPage],
    queryFn: async () => {
      return await previewStep({
        datasource_id: datasourceId,
        pipeline_steps: pipeline,
        target_step_id: stepId,
        row_limit: rowLimit,
        page: currentPage
      })
    },
    staleTime: 30000, // 30 seconds
    enabled: !!datasourceId && !!stepId && pipeline.length > 0
  })

  const data = $derived($query.data)
  const isLoading = $derived($query.isLoading)
  const error = $derived($query.error)

  function nextPage() {
    if (data && currentPage * rowLimit < data.total_rows) {
      currentPage++
    }
  }

  function prevPage() {
    if (currentPage > 1) {
      currentPage--
    }
  }
</script>

{#if isLoading}
  <div class="loading">Loading preview...</div>
{:else if error}
  <div class="error">Failed to load preview: {error.message}</div>
{:else if data}
  <div class="table-container">
    <div class="table-info">
      Showing {(currentPage - 1) * rowLimit + 1}-{Math.min(currentPage * rowLimit, data.total_rows)} of {data.total_rows} rows
    </div>
    
    <table>
      <thead>
        <tr>
          {#each data.columns as col}
            <th>{col}</th>
          {/each}
        </tr>
      </thead>
      <tbody>
        {#each data.data as row}
          <tr>
            {#each data.columns as col}
              <td>{row[col] ?? 'null'}</td>
            {/each}
          </tr>
        {/each}
      </tbody>
    </table>

    <div class="pagination">
      <button onclick={prevPage} disabled={currentPage === 1}>Previous</button>
      <span>Page {currentPage} of {Math.ceil(data.total_rows / rowLimit)}</span>
      <button onclick={nextPage} disabled={currentPage * rowLimit >= data.total_rows}>Next</button>
    </div>
  </div>
{:else}
  <div class="empty">No data available</div>
{/if}

<style>
  .table-container {
    width: 100%;
    overflow-x: auto;
    border: 1px solid var(--border-color);
    border-radius: 4px;
    margin: 8px 0;
  }

  .table-info {
    padding: 8px;
    font-size: 0.875rem;
    color: var(--text-secondary);
    background: var(--bg-secondary);
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.875rem;
  }

  th, td {
    padding: 8px 12px;
    text-align: left;
    border-bottom: 1px solid var(--border-color);
  }

  th {
    background: var(--bg-secondary);
    font-weight: 600;
    position: sticky;
    top: 0;
  }

  tbody tr:hover {
    background: var(--bg-hover);
  }

  .pagination {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px;
    background: var(--bg-secondary);
  }

  .pagination button {
    padding: 4px 12px;
    border: 1px solid var(--border-color);
    border-radius: 4px;
    background: white;
    cursor: pointer;
  }

  .pagination button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .loading, .error, .empty {
    padding: 16px;
    text-align: center;
    color: var(--text-secondary);
  }

  .error {
    color: var(--error-color);
  }
</style>
```

---

## Testing

### Unit Test

1. Mock TanStack Query
2. Test props binding
3. Test pagination logic
4. Test auto-refresh on pipeline change

### Integration Test

1. Create view step in pipeline
2. Verify table renders with data
3. Add filter step before view
4. Verify table auto-refreshes with filtered data
5. Test pagination buttons

---

## Status

- [x] Create InlineDataTable.svelte component
- [x] Implement TanStack Query integration
- [x] Add pagination controls
- [x] Style component (matching DataTable.svelte conventions)
- [x] Export from viewers/index.ts
- [x] TypeScript check passes
- [ ] Test auto-refresh on pipeline changes (pending integration)
- [ ] Test pagination (pending integration)

---

## Implementation Notes

### Features Implemented

✅ **Auto-fetch** - Query runs when datasourceId, stepId, and pipeline are available  
✅ **Auto-refresh** - Query key includes entire pipeline; changes trigger re-fetch  
✅ **Pagination** - Client-side pagination with Previous/Next buttons  
✅ **Loading states** - Spinner with "Loading preview..." message  
✅ **Error states** - Red error display with message  
✅ **Empty states** - "No data available" for null results  
✅ **Responsive table** - Horizontal scroll, sticky header, max 400px height  
✅ **Row info** - Shows "X-Y of Z rows" with locale formatting  

### TanStack Query Configuration

```typescript
createQuery(() => ({
  queryKey: ['step-preview', datasourceId, stepId, pipeline, currentPage],
  queryFn: async () => previewStepData({...}),
  staleTime: 30000, // 30 seconds cache
  enabled: !!datasourceId && !!stepId && pipeline.length > 0
}))
```

**Auto-refresh mechanism:** Including the full `pipeline` array in `queryKey` means any change to any step (config, order, add/remove) invalidates the cache and triggers a re-fetch.

### Styling

- Matches existing `DataTable.svelte` styling conventions
- Uses hex colors (#e5e7eb, #f9fafb, etc.) from project palette
- Monospace font for column names
- Max table height: 400px (vs 600px in DataTable for space in nodes)
- Font size: 0.875rem throughout

### Pagination

- Shows "Page X of Y" in footer
- Previous/Next buttons with disabled states
- Only renders pagination if more than 1 page
- Uses `currentPage` state variable - changing it triggers re-query

---

## Design Notes

### Auto-Refresh Mechanism

TanStack Query's `queryKey` includes the entire `pipeline` array. When any step in the pipeline changes (config update, step added/removed), the reference changes and TanStack Query automatically re-fetches the preview.

### Performance Considerations

- `staleTime: 30000` prevents excessive re-fetching
- `enabled` condition ensures query only runs when data is available
- Pagination happens client-side using pre-fetched 5000 rows from backend

### Styling

Uses CSS variables for theming:
- `--border-color`
- `--bg-secondary`
- `--bg-hover`
- `--text-secondary`
- `--error-color`

These should be defined in the app's global CSS.
