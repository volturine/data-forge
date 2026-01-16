# Frontend: Compute Preview API Client

**Priority:** HIGH  
**Status:** ✅ Complete  
**Depends On:** backend-compute/preview-endpoint.md ✅  
**Blocks:** frontend-viewers/inline-table.md ✅

---

## Goal

Add TypeScript API client for the new step preview endpoint to enable inline data fetching.

---

## Changes Required

### 1. Add Types

**File:** `frontend/src/lib/api/compute.ts`

Add after existing types:

```typescript
export interface StepPreviewRequest {
  datasource_id: string
  pipeline_steps: Array<{
    id: string
    type: string
    config: Record<string, unknown>
  }>
  target_step_id: string
  row_limit?: number
  page?: number
}

export interface StepPreviewResponse {
  step_id: string
  columns: string[]
  data: Array<Record<string, unknown>>
  total_rows: number
  page: number
  page_size: number
}
```

### 2. Add API Function

Add after existing functions:

```typescript
export async function previewStep(
  request: StepPreviewRequest
): Promise<StepPreviewResponse> {
  const response = await apiRequest<StepPreviewResponse>('/api/v1/compute/preview', {
    method: 'POST',
    body: JSON.stringify(request)
  })
  return response
}
```

### 3. Export New Function

Update exports at bottom of file:

```typescript
export { executeAnalysis, getJobStatus, getJobResult, cancelJob, previewStep }
```

---

## Testing

### Manual Test:

```typescript
// In browser console or test file
import { previewStep } from '$lib/api/compute'

const result = await previewStep({
  datasource_id: 'your-uuid-here',
  pipeline_steps: [
    { id: 'step1', type: 'filter', config: { column: 'age', operator: '>', value: 18 } }
  ],
  target_step_id: 'step1',
  row_limit: 100,
  page: 1
})

console.log(result)
// Should show: { step_id, columns, data, total_rows, page, page_size }
```

---

## Status

- [x] Add StepPreviewRequest/Response types
- [x] Add previewStepData() function
- [x] Export types and function
- [x] TypeScript check passes

---

## Implementation Notes

- Added `StepPreviewRequest` and `StepPreviewResponse` interfaces to `compute.ts`
- Kept existing `previewStep()` for backwards compatibility
- New function `previewStepData()` uses the new API contract
- All types are properly exported for use in components

---

## Next Steps

After completion, move to `frontend-viewers/inline-table.md` to build the UI component.
