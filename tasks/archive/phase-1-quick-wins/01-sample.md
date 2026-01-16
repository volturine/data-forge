# Task: Sample Operation

**Estimated Effort**: 2-3 hours
**Priority**: High
**Can Start**: Immediately
**Depends On**: None
**Parallel Safe**: Yes

## Description

Implement random sampling operation that allows users to sample rows from DataFrame either by count (n rows) or fraction (% of rows).

## Reference

See `tasks/tasks-missing-operations.md` lines 127-229 for full specification.

## Implementation Checklist

### Backend (1 hour)

- [ ] Add `sample` case to `_apply_step` in `backend/modules/compute/engine.py`
  ```python
  elif operation == 'sample':
      sample_type = params.get('sample_type', 'n')
      n = params.get('n', None)
      fraction = params.get('fraction', None)
      with_replacement = params.get('with_replacement', False)
      seed = params.get('seed', None)
      shuffle = params.get('shuffle', True)
      
      if sample_type == 'n' and n is not None:
          return df.sample(n=n, with_replacement=with_replacement, shuffle=shuffle, seed=seed)
      elif sample_type == 'fraction' and fraction is not None:
          return df.sample(fraction=fraction, with_replacement=with_replacement, shuffle=shuffle, seed=seed)
      else:
          raise ValueError('Must specify either n or fraction for sampling')
  ```
- [ ] Add `sample` to operation enum in backend schemas
- [ ] Write 5 backend tests:
  1. Sample by count (n=10)
  2. Sample by fraction (0.1)
  3. Sample with replacement
  4. Sample with seed (reproducibility)
  5. Invalid parameters (neither n nor fraction)

### Frontend (1 hour)

- [ ] Create `frontend/src/lib/components/operations/SampleConfig.svelte`
  - Sample type selector (by count / by fraction)
  - Number input for count (when sample_type='n')
  - Number input for fraction (when sample_type='fraction')
  - Checkbox for with_replacement
  - Checkbox for shuffle
  - Optional seed input
- [ ] Export from `frontend/src/lib/components/operations/index.ts`
- [ ] Follow existing style (match FilterConfig.svelte)
- [ ] Use Svelte 5 runes only

### Integration (30 min)

- [ ] Add to `StepLibrary.svelte` operations palette
- [ ] Add schema calculation to `transformation-rules.ts`
  - Preserves all columns and types
  - Updates row count (cannot be determined exactly)
- [ ] Manual UI testing

### Testing (30 min)

- [ ] Run backend tests: `cd backend && uv run pytest -k sample`
- [ ] Write 2 component tests
- [ ] Check for LSP errors: `cd frontend && npm run check`

## Acceptance Criteria

- [ ] User can select sample type (count or fraction)
- [ ] User can specify sample parameters
- [ ] Operation appears in StepLibrary palette
- [ ] Backend tests pass (5/5)
- [ ] No TypeScript errors
- [ ] Sample with seed produces reproducible results
- [ ] Invalid config shows clear error message

## Files to Modify

1. `backend/modules/compute/engine.py` - Add operation
2. `frontend/src/lib/components/operations/SampleConfig.svelte` - New file
3. `frontend/src/lib/components/operations/index.ts` - Export
4. `frontend/src/lib/components/StepLibrary.svelte` - Add to palette
5. `frontend/src/lib/stores/transformation-rules.ts` - Schema calculation
6. `backend/tests/modules/compute/test_engine.py` - Add tests

## Testing Commands

```bash
# Backend tests
cd backend && uv run pytest -k sample -v

# Type check
cd frontend && npm run check

# Full test suite
cd backend && uv run pytest
cd frontend && npm run test
```

## Notes

- Sample is one of the most commonly used operations
- Seed parameter important for reproducibility
- Both count and fraction modes are useful
- Simple schema transformation (preserves columns)
