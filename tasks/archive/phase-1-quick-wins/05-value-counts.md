# Task: Value Counts Operation

**Estimated Effort**: 3-4 hours
**Priority**: High
**Can Start**: Immediately
**Depends On**: None
**Parallel Safe**: Yes

## Description

Implement value_counts operation that returns frequency counts of unique values in a column. Essential for categorical data analysis and data profiling.

## Reference

See `tasks/tasks-missing-operations.md` lines 995-1068 for full specification.

## Implementation Checklist

### Backend (1.5 hours)

- [ ] Add `value_counts` case to `_apply_step` in `backend/modules/compute/engine.py`
  ```python
  elif operation == 'value_counts':
      column = params.get('column')
      sort = params.get('sort', True)
      parallel = params.get('parallel', False)
      
      # Value counts returns a struct, need to unnest
      result = df.select(pl.col(column).value_counts(sort=sort, parallel=parallel))
      return result.unnest(column)
  ```
- [ ] Add `value_counts` to operation enum in backend schemas
- [ ] Write 5 backend tests:
  1. Value counts on string column
  2. Value counts on numeric column
  3. Value counts with sort=True
  4. Value counts with sort=False
  5. Value counts with null values

### Frontend (1 hour)

- [ ] Create `frontend/src/lib/components/operations/ValueCountsConfig.svelte`
  - Select/dropdown for column selection
  - Checkbox for "Sort by count (descending)"
  - Show column type in selector
- [ ] Export from `frontend/src/lib/components/operations/index.ts`
- [ ] Follow existing style
- [ ] Use Svelte 5 runes only

### Integration (30 min)

- [ ] Add to `StepLibrary.svelte` operations palette
- [ ] Add schema calculation to `transformation-rules.ts`
  - Returns 2 columns: [column_name, "count"]
  - First column type matches original
  - Second column is Int64
- [ ] Manual UI testing

### Testing (30-60 min)

- [ ] Run backend tests: `cd backend && uv run pytest -k value_counts`
- [ ] Write 2 component tests
- [ ] Check for LSP errors: `cd frontend && npm run check`

## Acceptance Criteria

- [ ] User can select column to analyze
- [ ] User can toggle sort option
- [ ] Operation appears in StepLibrary palette
- [ ] Backend tests pass (5/5)
- [ ] No TypeScript errors
- [ ] Output has correct schema (value + count columns)
- [ ] Sort option works correctly
- [ ] Handles null values properly

## Files to Modify

1. `backend/modules/compute/engine.py` - Add operation
2. `frontend/src/lib/components/operations/ValueCountsConfig.svelte` - New file
3. `frontend/src/lib/components/operations/index.ts` - Export
4. `frontend/src/lib/components/StepLibrary.svelte` - Add to palette
5. `frontend/src/lib/stores/transformation-rules.ts` - Schema calculation
6. `backend/tests/modules/compute/test_engine.py` - Add tests

## Testing Commands

```bash
# Backend tests
cd backend && uv run pytest -k value_counts -v

# Type check
cd frontend && npm run check

# Full test suite
cd backend && uv run pytest
cd frontend && npm run test
```

## Notes

- Very useful for categorical data analysis
- Important to unnest the struct returned by Polars
- Schema calculation needs to create 2 columns
- Consider adding parallel option in UI (advanced checkbox)
- Sorted output is usually most useful (default True)
