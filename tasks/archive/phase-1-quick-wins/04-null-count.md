# Task: Null Count Operation

**Estimated Effort**: 2 hours
**Priority**: High (Data Quality)
**Can Start**: Immediately
**Depends On**: None
**Parallel Safe**: Yes

## Description

Implement null_count operation that returns statistics about null values in each column. Essential for data quality assessment.

## Reference

See `tasks/tasks-missing-operations.md` lines 961-992 for full specification.

## Implementation Checklist

### Backend (45 min)

- [ ] Add `null_count` case to `_apply_step` in `backend/modules/compute/engine.py`
  ```python
  elif operation == 'null_count':
      return df.null_count()
  ```
- [ ] Add `null_count` to operation enum in backend schemas
- [ ] Write 3 backend tests:
  1. Null count on dataframe with nulls
  2. Null count on dataframe without nulls
  3. Null count on empty dataframe

### Frontend (30 min)

- [ ] Create `frontend/src/lib/components/operations/NullCountConfig.svelte`
  - Very simple component, possibly just info text
  - No configuration needed (operation has no parameters)
  - Just show "This operation counts null values in each column"
- [ ] Export from `frontend/src/lib/components/operations/index.ts`
- [ ] Use Svelte 5 runes

### Integration (30 min)

- [ ] Add to `StepLibrary.svelte` operations palette
- [ ] Add schema calculation to `transformation-rules.ts`
  - Returns single row
  - All columns become Int64 type (count values)
  - Column names preserved
- [ ] Manual UI testing

### Testing (15 min)

- [ ] Run backend tests: `cd backend && uv run pytest -k null_count`
- [ ] Write 1 component test (rendering)
- [ ] Check for LSP errors: `cd frontend && npm run check`

## Acceptance Criteria

- [ ] Operation appears in StepLibrary palette
- [ ] Backend tests pass (3/3)
- [ ] No TypeScript errors
- [ ] Result shows one row with null counts
- [ ] All output columns are Int64 type
- [ ] Works on dataframes with/without nulls

## Files to Modify

1. `backend/modules/compute/engine.py` - Add operation
2. `frontend/src/lib/components/operations/NullCountConfig.svelte` - New file
3. `frontend/src/lib/components/operations/index.ts` - Export
4. `frontend/src/lib/components/StepLibrary.svelte` - Add to palette
5. `frontend/src/lib/stores/transformation-rules.ts` - Schema calculation
6. `backend/tests/modules/compute/test_engine.py` - Add tests

## Testing Commands

```bash
# Backend tests
cd backend && uv run pytest -k null_count -v

# Type check
cd frontend && npm run check

# Full test suite
cd backend && uv run pytest
cd frontend && npm run test
```

## Notes

- Simplest operation in this phase
- No user configuration required
- Very useful for data profiling
- Output is always one row with Int64 columns
- Consider combining with describe() or profile() in future
