# Critical Fixes - Parallel Implementation Plan

**Created:** 2026-01-16
**Priority:** CRITICAL
**Execution Mode:** PARALLEL

---

## Task Breakdown

### Task 1: Fix 14 Operation Config Components Dark Mode
**Assignee:** Agent 1
**Priority:** CRITICAL
**Estimated Time:** 20 minutes

**Files to Modify:**
1. `frontend/src/lib/components/operations/FilterConfig.svelte`
2. `frontend/src/lib/components/operations/SelectConfig.svelte`
3. `frontend/src/lib/components/operations/GroupByConfig.svelte`
4. `frontend/src/lib/components/operations/SortConfig.svelte`
5. `frontend/src/lib/components/operations/RenameConfig.svelte`
6. `frontend/src/lib/components/operations/DropConfig.svelte`
7. `frontend/src/lib/components/operations/JoinConfig.svelte`
8. `frontend/src/lib/components/operations/ExpressionConfig.svelte`
9. `frontend/src/lib/components/operations/DeduplicateConfig.svelte`
10. `frontend/src/lib/components/operations/FillNullConfig.svelte`
11. `frontend/src/lib/components/operations/ExplodeConfig.svelte`
12. `frontend/src/lib/components/operations/PivotConfig.svelte`
13. `frontend/src/lib/components/operations/TimeSeriesConfig.svelte`
14. `frontend/src/lib/components/operations/StringMethodsConfig.svelte`

**Color Mapping:**
```css
/* Borders */
#ddd, #ccc, #dee2e6, #e5e7eb → var(--border-primary)
#333, #404040 → var(--border-secondary)

/* Backgrounds */
#f8f9fa, #f9fafb, #f0f1f5 → var(--bg-tertiary)
white, #fff, #ffffff → var(--bg-primary)
#e9ecef → var(--bg-hover)

/* Text */
#333, #495057, #212529, #111827 → var(--fg-primary)
#6c757d, #6b7280 → var(--fg-muted)
#000, #000000 → var(--fg-primary)

/* Buttons/Actions */
#007bff, #0d6efd → var(--accent-primary)
#28a745, #198754 → var(--success-fg)
#dc3545, #dc2626 → var(--error-fg)
#ffc107 → var(--warning-border)

/* Highlights */
#e7f3ff, #d1ecf1 → var(--accent-bg)
#fff3cd → var(--warning-bg)
```

---

### Task 2: Fix Results Export Hardcoded URL
**Assignee:** Agent 2
**Priority:** CRITICAL
**Estimated Time:** 5 minutes

**File to Modify:**
- `frontend/src/lib/api/results.ts`

**Changes:**
1. Import `BASE_URL` from `./client`
2. Replace `${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/api/v1/results/...` with `${BASE_URL}/api/v1/results/...`
3. Ensure consistency with other API calls

---

### Task 3: Multi-Condition Filter Support
**Assignee:** Agent 3
**Priority:** CRITICAL
**Estimated Time:** 30 minutes

**Files to Modify:**
1. `backend/modules/compute/step_converter.py` - `convert_filter_config()`
2. `backend/modules/compute/engine.py` - `_apply_step()` filter operation

**Implementation:**
1. Parse ALL conditions from frontend (not just first)
2. Build Polars expression chains for AND/OR logic
3. Support operators: `=`, `!=`, `>`, `<`, `>=`, `<=`, `contains`, `starts_with`, `ends_with`
4. Combine conditions with AND/OR based on `logic` field

**Example Logic:**
```python
def build_filter_expression(conditions, logic='AND'):
    exprs = []
    for cond in conditions:
        col = pl.col(cond['column'])
        op = cond['operator']
        val = cond['value']
        
        if op == '=' or op == '==':
            expr = col == val
        elif op == '!=':
            expr = col != val
        # ... etc
        
        exprs.append(expr)
    
    if logic == 'AND':
        return pl.all_horizontal(exprs)
    else:  # OR
        return pl.any_horizontal(exprs)
```

---

### Task 4: Add Missing Frontend API Functions
**Assignee:** Agent 4
**Priority:** CRITICAL
**Estimated Time:** 15 minutes

**Files to Create/Modify:**

1. **Health Check** - `frontend/src/lib/api/health.ts` (NEW)
   ```typescript
   export async function checkHealth() {
       return apiRequest('/api/v1/health/');
   }
   ```

2. **Datasource Functions** - `frontend/src/lib/api/datasource.ts`
   - Add `getDatasource(id: string)` - GET single datasource
   
3. **Analysis Linking** - `frontend/src/lib/api/analysis.ts`
   - Add `linkDatasource(analysisId, datasourceId)` - POST link
   - Add `unlinkDatasource(analysisId, datasourceId)` - DELETE unlink

4. **Compute Cleanup** - `frontend/src/lib/api/compute.ts`
   - Add `cleanupJob(jobId: string)` - DELETE cleanup

5. **Results Deletion** - `frontend/src/lib/api/results.ts`
   - Add `deleteResult(analysisId: string)` - DELETE result

---

### Task 5: Add Table/View Operation Node
**Assignee:** Agent 5
**Priority:** CRITICAL
**Estimated Time:** 40 minutes

**Files to Create/Modify:**

1. **Backend Operation Support** - `backend/modules/compute/engine.py`
   - Add `view` operation to `_apply_step()`
   - Operation simply returns df unchanged (passthrough for visualization)

2. **Frontend Operation Definition** - Add to step library
   - Type: `view`
   - Icon: 📊 or 🔍
   - Description: "Preview data at this step"
   - Config: minimal or none

3. **New Config Component** - `frontend/src/lib/components/operations/ViewConfig.svelte` (NEW)
   ```svelte
   <script lang="ts">
       let { config, onUpdate } = $props();
       
       // Minimal config - maybe just row limit
       let rowLimit = $state(config.rowLimit || 100);
       
       $effect(() => {
           onUpdate({ rowLimit });
       });
   </script>
   
   <div class="config-section">
       <label>
           Preview Rows
           <input type="number" bind:value={rowLimit} min="10" max="1000" />
       </label>
       <p class="help-text">Number of rows to display (10-1000)</p>
   </div>
   ```

4. **Update Step Library** - `frontend/src/lib/components/pipeline/StepLibrary.svelte`
   - Add view step to available operations

5. **Update Step Config Router** - `frontend/src/lib/components/pipeline/StepConfig.svelte`
   - Import and route to ViewConfig

6. **Backend Converter** - `backend/modules/compute/step_converter.py`
   - Add converter for `view` operation (passthrough)

---

## Execution Order

**PARALLEL TRACKS:**

1. **Track A (Frontend Styling):** Task 1 - Operation configs dark mode
2. **Track B (API Fixes):** Task 2 - Results export + Task 4 - Missing APIs
3. **Track C (Backend Logic):** Task 3 - Multi-condition filters
4. **Track D (New Feature):** Task 5 - Table/View operation

**Estimated Total Time:** 40 minutes (parallel) vs 110 minutes (sequential)

---

## Testing Checklist

After all tasks complete:

- [ ] All operation config panels properly themed in dark mode
- [ ] Results export uses correct BASE_URL (test in dev mode)
- [ ] Filter with multiple conditions (AND logic)
- [ ] Filter with multiple conditions (OR logic)
- [ ] Filter with all operators (=, !=, >, <, >=, <=, contains)
- [ ] Health check API callable from frontend
- [ ] Get single datasource works
- [ ] Link/unlink datasource to analysis
- [ ] Cleanup job API works
- [ ] Delete result API works
- [ ] View/table node insertable in pipeline
- [ ] View node displays data preview
- [ ] View node doesn't modify data (passthrough)

---

## Success Criteria

All tasks marked DONE when:
1. ✅ All 14 operation configs use CSS variables (no hardcoded colors)
2. ✅ Results export uses BASE_URL consistently
3. ✅ Filters support multiple conditions with AND/OR
4. ✅ All 8 missing API functions implemented and tested
5. ✅ View/table operation node fully functional

---

## Notes

- Use subagents for parallel execution
- Each track is independent and can run simultaneously
- Testing should happen after all tracks complete
- Delete this file after all tasks verified complete
