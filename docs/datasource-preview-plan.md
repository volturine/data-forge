# Datasource Preview Implementation Plan

## Overview

Add inline datasource preview functionality to the datasources list page, allowing users to view sample data and schema without creating an analysis.

## Key Discovery

The backend `/v1/compute/preview` endpoint already supports datasource preview by accepting an empty `pipeline_steps` array. No backend changes needed.

## Implementation Approach: Inline Expansion

### Why Inline Expansion?

- Matches existing `StepNode.svelte` preview pattern (`.view-preview.expanded`)
- Keeps users in context - no navigation disruption
- Simpler than modals or side panels
- Mobile-friendly
- Only one preview open at a time

### UI Flow

```
User clicks datasource row
  → Preview expands below the row
  → Shows data table with pagination (default 100 rows)
  → Toggle between Data and Schema views
  → Click row again to collapse
```

## Files to Create

### 1. `/frontend/src/lib/components/datasources/DatasourcePreview.svelte`

**Purpose**: Wrapper component for preview functionality

**Features**:

- View toggle: "Data" | "Schema"
- Uses `@tanstack/svelte-query` for data fetching
- Reuses `InlineDataTable.svelte` for data display
- Reuses `SchemaViewer.svelte` for schema display
- Loading/error states

**Query Setup**:

```typescript
createQuery(() => ({
  queryKey: ["datasource-preview", datasourceId, page],
  queryFn: async () => {
    return await previewStepData({
      datasource_id: datasourceId,
      pipeline_steps: [], // Empty = raw datasource
      target_step_id: "source",
      row_limit: 100,
      page: page,
    });
  },
  staleTime: 30000, // 30 second cache
}));
```

**Layout**:

- Header with view toggle buttons
- Conditional rendering based on active view
- Styled with existing design tokens

## Files to Modify

### 1. `/frontend/src/routes/datasources/+page.svelte`

**State Additions**:

```typescript
let expandedPreview = $state<string | null>(null);
```

**Changes**:

1. Import `ChevronDown` and `ChevronRight` from `lucide-svelte`
2. Import `DatasourcePreview` component
3. Add click handler to table rows:
   ```typescript
   function togglePreview(id: string) {
     expandedPreview = expandedPreview === id ? null : id;
   }
   ```
4. Add chevron icon to first column showing expansion state
5. Add preview row after each datasource row:
   ```svelte
   {#if expandedPreview === datasource.id}
     <tr class="preview-row">
       <td colspan="6">
         <DatasourcePreview datasourceId={datasource.id} />
       </td>
     </tr>
   {/if}
   ```
6. Add CSS for smooth expansion animation

## API Integration

**No backend changes required**. Uses existing:

- Endpoint: `POST /v1/compute/preview`
- Frontend function: `previewStepData()` from `/frontend/src/lib/api/compute.ts`

**Request**:

```json
{
  "datasource_id": "uuid",
  "pipeline_steps": [],
  "target_step_id": "source",
  "row_limit": 100,
  "page": 1
}
```

**Response**: Standard `StepPreviewResponse` with columns, data, total_rows, pagination info

## Components Reused (No Changes)

- `/frontend/src/lib/components/viewers/InlineDataTable.svelte` - Data display
- `/frontend/src/lib/components/viewers/SchemaViewer.svelte` - Schema display
- Existing API client functions

## Edge Cases Handled

1. **Loading**: Skeleton/spinner shown during fetch
2. **Errors**: Inline error message with retry option
3. **Empty datasources**: "No data available" message
4. **Large datasets**: Pagination (handled by InlineDataTable)
5. **Multiple previews**: Only one open at a time
6. **Concurrent deletes**: Query fails gracefully, preview disappears
7. **Schema unavailable**: Fallback to column types from preview data

## Styling

**Design Tokens**:

- `--bg-primary`, `--bg-hover` - backgrounds
- `--border-primary` - borders
- `--panel-bg`, `--panel-border` - component styling
- `--transition` - smooth animations
- `--space-*` - consistent spacing

**Animation**:

```css
.preview-row {
  animation: expandDown 0.2s ease-out;
}
```

## Accessibility

- `aria-expanded` on clickable rows
- Keyboard support: Enter/Space to toggle
- Focus management
- Screen reader announcements for states

## Verification

### Manual Testing

1. Navigate to `/datasources` page
2. Click on a datasource row
3. Verify preview expands with data table
4. Test pagination (next/prev buttons)
5. Toggle to Schema view
6. Click row again to collapse
7. Test with different datasource types (CSV, Parquet, database)
8. Test error state (delete datasource while preview open)
9. Test empty datasource (0 rows)

### Expected Behavior

- Preview shows actual row data from datasource
- Pagination shows "Showing X-Y of Z rows"
- Schema view shows column names, types, nullable status
- Only one preview open at a time
- Smooth expand/collapse animation
- Loading states during data fetch

### Critical Files

1. `/frontend/src/lib/components/datasources/DatasourcePreview.svelte` (create)
2. `/frontend/src/routes/datasources/+page.svelte` (modify)
