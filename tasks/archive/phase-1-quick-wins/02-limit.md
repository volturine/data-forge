# Task: Head/Tail/Limit Operation

**Estimated Effort**: 2-3 hours
**Priority**: High
**Can Start**: Immediately
**Depends On**: None
**Parallel Safe**: Yes

## Description

Implement head/tail/limit operation for selecting first N rows (head), last N rows (tail), or limiting to N rows. Essential for data preview and testing.

## Reference

See `tasks/tasks-missing-operations.md` lines 364-434 for full specification.

## Implementation Checklist

### Backend (45 min)

- [ ] Add `limit` case to `_apply_step` in `backend/modules/compute/engine.py`
  ```python
  elif operation == 'limit':
      limit_type = params.get('limit_type', 'head')
      n = params.get('n', 10)
      
      if limit_type == 'head':
          return df.head(n)
      elif limit_type == 'tail':
          return df.tail(n)
      elif limit_type == 'limit':
          return df.limit(n)
      else:
          raise ValueError(f'Unsupported limit type: {limit_type}')
  ```
- [ ] Add `limit` to operation enum in backend schemas
- [ ] Write 4 backend tests:
  1. Head operation (first 10 rows)
  2. Tail operation (last 10 rows)
  3. Limit operation (first N rows)
  4. Edge case (n larger than dataframe)

### Frontend (45 min)

- [ ] Create `frontend/src/lib/components/operations/LimitConfig.svelte`
  - Select for operation type (head/tail/limit)
  - Number input for n (default 10)
  - Simple, minimal UI
- [ ] Export from `frontend/src/lib/components/operations/index.ts`
- [ ] Follow existing style
- [ ] Use Svelte 5 runes only

### Integration (30 min)

- [ ] Add to `StepLibrary.svelte` operations palette
- [ ] Add schema calculation to `transformation-rules.ts`
  - Preserves all columns and types
  - Updates row count to min(n, current_rows)
- [ ] Manual UI testing

### Testing (30 min)

- [ ] Run backend tests: `cd backend && uv run pytest -k limit`
- [ ] Write 2 component tests
- [ ] Check for LSP errors: `cd frontend && npm run check`

## Acceptance Criteria

- [ ] User can select operation type (head/tail/limit)
- [ ] User can specify number of rows
- [ ] Operation appears in StepLibrary palette
- [ ] Backend tests pass (4/4)
- [ ] No TypeScript errors
- [ ] Works correctly when n > total rows
- [ ] Default value of 10 is set

## Files to Modify

1. `backend/modules/compute/engine.py` - Add operation
2. `frontend/src/lib/components/operations/LimitConfig.svelte` - New file
3. `frontend/src/lib/components/operations/index.ts` - Export
4. `frontend/src/lib/components/StepLibrary.svelte` - Add to palette
5. `frontend/src/lib/stores/transformation-rules.ts` - Schema calculation
6. `backend/tests/modules/compute/test_engine.py` - Add tests

## Testing Commands

```bash
# Backend tests
cd backend && uv run pytest -k limit -v

# Type check
cd frontend && npm run check

# Full test suite
cd backend && uv run pytest
cd frontend && npm run test
```

## Notes

- Very simple operation, quick to implement
- Extremely useful for data preview
- All three modes (head/tail/limit) use native Polars methods
- Consider showing "showing X of Y rows" in UI
