# Operation Config Migration to $bindable()

**Status:** IN PROGRESS ⏳
**Started:** 2026-01-16
**Type:** Big Bang Migration
**Goal:** Migrate 15 operation config components from callback pattern to $bindable() rune

---

## Migration Overview

**Problem:**
- 52 `state_referenced_locally` warnings
- Callback-based pattern with manual Save/Cancel
- Local state copies in every config component

**Solution:**
- Use `$bindable()` rune for two-way binding
- Remove `onSave` callbacks and local state
- Enable live reactive updates

---

## Progress Tracker

### Phase 0: Task Organization ✅
- [x] Archive old tasks
- [x] Create migration tracker

### Phase 1: Update Parent Components
- [ ] StepConfig.svelte - Remove callbacks, add bind:config
- [ ] analysis/[id]/+page.svelte - Remove handleUpdateStep

### Phase 2: Migrate Operation Configs (15 files)
- [ ] FilterConfig.svelte
- [ ] SelectConfig.svelte (special: SvelteSet)
- [ ] GroupByConfig.svelte
- [ ] SortConfig.svelte
- [ ] RenameConfig.svelte
- [ ] DropConfig.svelte (special: SvelteSet)
- [ ] JoinConfig.svelte
- [ ] ExpressionConfig.svelte
- [ ] DeduplicateConfig.svelte
- [ ] FillNullConfig.svelte
- [ ] ExplodeConfig.svelte
- [ ] PivotConfig.svelte
- [ ] TimeSeriesConfig.svelte
- [ ] StringMethodsConfig.svelte
- [ ] ViewConfig.svelte

### Phase 3: Validation
- [ ] npm run check (0 errors, 0-4 warnings)
- [ ] npm run lint
- [ ] npm run build
- [ ] Manual testing (15 operations)

### Phase 4: Cleanup
- [ ] Update tasks folder
- [ ] Create completion summary

---

## Files Modified

**Parent Components (2):**
1. `frontend/src/lib/components/pipeline/StepConfig.svelte`
2. `frontend/src/routes/analysis/[id]/+page.svelte`

**Operation Configs (15):**
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
15. `frontend/src/lib/components/operations/ViewConfig.svelte`

**Total:** 17 files

---

## Key Pattern

**Before (callback pattern):**
```svelte
<script lang="ts">
  let { schema, config, onSave } = $props();
  let localConfig = $state({ ...config }); // ⚠️ Warning!
  
  function handleSave() {
    onSave(localConfig);
  }
</script>

<input bind:value={localConfig.field} />
<button onclick={handleSave}>Save</button>
```

**After ($bindable pattern):**
```svelte
<script lang="ts">
  let { 
    schema, 
    config = $bindable({ field: 'default' })
  } = $props();
</script>

<input bind:value={config.field} />
<!-- Changes auto-propagate! No Save button needed -->
```

---

## Expected Results

**Before:**
- 64 warnings total
- 52 state_referenced_locally warnings
- Manual Save/Cancel UX

**After:**
- 0-4 warnings (only css/navigation)
- 0 state_referenced_locally warnings
- Live reactive UX

---

## Notes

- Existing autosave (3s debounce) prevents data loss
- SelectConfig/DropConfig need special $effect for SvelteSet sync
- Type safety maintained via $bindable() defaults
