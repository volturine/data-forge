# Task: Top K / Bottom K Operation

**Estimated Effort**: 3-4 hours
**Priority**: High
**Can Start**: Immediately
**Depends On**: None
**Parallel Safe**: Yes

## Description

Implement top_k/bottom_k operation for finding highest/lowest N rows based on column values. More efficient than sort + limit for finding extremes.

## Reference

See `tasks/tasks-missing-operations.md` lines 877-958 for full specification.

## Implementation Checklist

### Backend (1.5 hours)

- [ ] Add `top_k` case to `_apply_step` in `backend/modules/compute/engine.py`
  ```python
  elif operation == 'top_k':
      k = params.get('k', 10)
      by = params.get('by', [])
      operation_type = params.get('operation_type', 'top')
      
      if operation_type == 'top':
          return df.top_k(k, by=by)
      elif operation_type == 'bottom':
          return df.bottom_k(k, by=by)
      else:
          raise ValueError(f'Unsupported operation type: {operation_type}')
  ```
- [ ] Add `top_k` to operation enum in backend schemas
- [ ] Write 5 backend tests:
  1. Top K by single column
  2. Bottom K by single column
  3. Top K by multiple columns
  4. Edge case (k larger than dataframe)
  5. Error case (empty 'by' list)

### Frontend (1.5 hours)

- [ ] Create `frontend/src/lib/components/operations/TopKConfig.svelte`
  - Select for operation type (top/bottom)
  - Number input for k (default 10)
  - Multi-select for columns to sort by
  - Show selected columns count
- [ ] Export from `frontend/src/lib/components/operations/index.ts`
- [ ] Follow existing style (similar to SortConfig)
- [ ] Use Svelte 5 runes only

### Integration (30 min)

- [ ] Add to `StepLibrary.svelte` operations palette
- [ ] Add schema calculation to `transformation-rules.ts`
  - Preserves all columns and types
  - Updates row count to min(k, current_rows)
- [ ] Manual UI testing

### Testing (30 min)

- [ ] Run backend tests: `cd backend && uv run pytest -k top_k`
- [ ] Write 2 component tests
- [ ] Check for LSP errors: `cd frontend && npm run check`

## Acceptance Criteria

- [ ] User can select top or bottom K
- [ ] User can specify K value
- [ ] User can select one or more columns to sort by
- [ ] Operation appears in StepLibrary palette
- [ ] Backend tests pass (5/5)
- [ ] No TypeScript errors
- [ ] Multi-column sorting works correctly
- [ ] Clear error when no columns selected

## Files to Modify

1. `backend/modules/compute/engine.py` - Add operation
2. `frontend/src/lib/components/operations/TopKConfig.svelte` - New file
3. `frontend/src/lib/components/operations/index.ts` - Export
4. `frontend/src/lib/components/StepLibrary.svelte` - Add to palette
5. `frontend/src/lib/stores/transformation-rules.ts` - Schema calculation
6. `backend/tests/modules/compute/test_engine.py` - Add tests

## Testing Commands

```bash
# Backend tests
cd backend && uv run pytest -k top_k -v

# Type check
cd frontend && npm run check

# Full test suite
cd backend && uv run pytest
cd frontend && npm run test
```

## Notes

- More efficient than sort + limit for large datasets
- Useful for leaderboards, top performers, etc.
- Multi-column support allows breaking ties
- Consider adding validation for empty 'by' list
