# Inline View Migration - Master Task

**Goal:** Implement real-time lazy data pipeline with inline view components

**Status:** ✅ Complete (Ready for Testing)

**Started:** 2026-01-16  
**Completed:** 2026-01-16

---

## Architecture Changes

### Current Flow:
```
User → Add steps → Click Run → See results in footer panel
```

### New Flow:
```
User → Add/Edit steps → Auto-execute (lazy) → View steps show inline data
```

---

## Task Breakdown

### Backend Tasks (Parallel)
- [x] `backend-compute/lazy-polars.md` - Convert to LazyFrame evaluation ✅
- [x] `backend-compute/preview-endpoint.md` - Add step preview API ✅

### Frontend Tasks (Parallel)
- [x] `frontend-api/compute-preview.md` - Add preview API client ✅
- [x] `frontend-viewers/inline-table.md` - Create InlineDataTable component ✅
- [x] `frontend-pipeline/view-integration.md` - Wire up view to pipeline ✅
- [x] `frontend-editor/remove-run-button.md` - Remove run button & footer ✅

### Optimization Tasks (After core)
- [ ] `frontend-editor/debounce-autosave.md` - Optimize auto-save

---

## Key Decisions

1. **Auto-fetch:** View steps fetch preview immediately on addition ✅
2. **Auto-refresh:** View re-fetches when upstream steps change ✅  
3. **Multiple views:** Allowed at any pipeline position ✅
4. **Pagination:** 1000 rows per view, paginated ✅
5. **Run button:** Removed - views drive computation ✅
6. **Lazy loading:** Full lazy evaluation with scan_* ✅

---

## Dependencies

```
backend-compute/lazy-polars.md
  ↓
backend-compute/preview-endpoint.md
  ↓
frontend-api/compute-preview.md
  ↓
frontend-viewers/inline-table.md
  ↓
frontend-pipeline/view-integration.md
  ↓
frontend-editor/remove-run-button.md
  ↓
frontend-editor/debounce-autosave.md
```

---

## Testing Checklist

- [ ] Upload CSV → Add view → See inline data
- [ ] Add filter → View auto-refreshes with filtered data
- [ ] Multiple views show different intermediate states
- [ ] Large files (100MB+) load quickly via lazy scan
- [ ] Pagination works (1000 rows, multiple pages)
- [ ] No UI freezing with auto-save

---

## Notes

- Using TanStack Query for auto-refresh on dependency changes
- Backend caching can be added later for performance
- Export feature postponed to Phase 2
