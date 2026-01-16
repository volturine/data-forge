# Frontend: Remove Run Button & Results Footer

**Priority:** HIGH  
**Status:** ✅ Complete  
**Depends On:** frontend-pipeline/view-integration.md ✅  
**Blocks:** None

---

## Goal

Remove the "Run" button and results footer panel since view steps now provide real-time inline data previews. The old execution flow is no longer needed.

---

## Changes Required

### 1. Remove Run Button from Header

**File:** `frontend/src/routes/analysis/[id]/+page.svelte`

Find and remove the Run button from the editor header.

### 2. Remove Results Footer Panel

Remove the entire results panel section that displays at the bottom of the page.

### 3. Clean Up Related State

Remove state variables and functions related to:
- `showResults`
- `isRunning`
- Job polling logic
- Result data queries

### 4. Clean Up Imports

Remove unused imports:
- `getResultData` from `$lib/api/results`
- `computeStore` if no longer needed
- `executeAnalysis` if no longer needed

---

## Implementation

Will identify and remove:
1. Run button component/element
2. Results panel component/section
3. Related state variables
4. Related event handlers
5. Related queries/data fetching
6. Unused imports

---

## Status

- [x] Located and removed Run button (lines 213-220)
- [x] Located and removed results footer panel (lines 233-301)
- [x] Removed related state variables (showResults, isRunning)
- [x] Removed related functions/handlers (handleRun)
- [x] Removed related derived values (currentJob, resultQuery)
- [x] Removed unused imports (computeStore, getResultData, DataTable)
- [x] Removed unused CSS (.btn-primary, .btn-icon, .results-*)
- [x] TypeScript check passes (0 errors, back to 5 pre-existing warnings)

---

## Implementation Summary

### Removed Code

**Imports (3):**
- `computeStore` from `$lib/stores/compute.svelte`
- `getResultData` from `$lib/api/results`
- `DataTable` from `$lib/components/viewers/DataTable.svelte`

**State Variables (2):**
- `showResults` - controlled results panel visibility
- `isRunning` - tracked execution state

**Derived Values (2):**
- `currentJob` - latest compute job for the analysis
- `resultQuery` - TanStack Query for fetching results

**Functions (1):**
- `handleRun()` - async function to execute analysis

**Markup (2 sections):**
- Run button (8 lines) - in header actions
- Results panel (68 lines) - entire footer section with:
  - Results header with close button
  - Job status display
  - Loading/error/empty states
  - DataTable for completed results
  - Progress bar

**CSS (13 rules, 103 lines):**
- `.results-panel` - panel container
- `.results-header` - header section
- `.results-actions` - action buttons container  
- `.job-status` + variants - status badges
- `.results-content` - scrollable content area
- `.results-loading/error/empty` - state displays
- `.progress-bar/fill` - progress indicator
- `.btn-primary` + variants - primary button styles
- `.btn-icon` + hover - icon button styles

### File Stats

**Before:** 682 lines  
**After:** 463 lines  
**Removed:** 219 lines (32% reduction)

### Breaking Changes

This completely removes the old execution model:
- Users can no longer click "Run" to execute the full pipeline
- Results are no longer shown in a footer panel
- **New model:** Users add View steps to see data at any pipeline position
- View steps provide real-time, lazy-evaluated previews inline

---

## Testing Notes

After cleanup:
- ✅ Page loads without errors
- ✅ No Run button in header (only Back, Save)
- ✅ No results panel at bottom
- ✅ Add/edit steps work normally
- ✅ View steps show inline data (when integrated)
- ✅ TypeScript check passes

---

## Migration Impact

**Old Workflow:**
```
Add steps → Click Run → Wait → See results in footer
```

**New Workflow:**
```
Add steps → Add View step → See data inline immediately
```

**Advantages:**
- Instant feedback (no waiting for execution)
- Multiple views possible (see intermediate data)
- Lazy evaluation (faster for large datasets)
- Better visual connection (data next to step)

**Trade-offs:**
- Must explicitly add View steps to see data
- No "final results" panel (intentional - users control where they view)


---

## Testing

After cleanup:
1. Open analysis page
2. Verify no Run button in header
3. Verify no results panel at bottom
4. Add/edit steps - should work normally
5. Add view steps - should show inline data
6. No console errors

---

## Notes

This is a **breaking change** that removes the old execution model. After this:
- Users can only see data via View steps (not via Run button)
- This enforces the new lazy evaluation + inline view architecture
- Old execution/polling logic is completely removed
