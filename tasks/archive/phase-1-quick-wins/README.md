# Phase 1 - Quick Wins

**Status**: Ready to Start
**Total Estimated Effort**: 12-16 hours
**Priority**: High
**Parallelization**: All tasks can be done concurrently

## Overview

These are high-priority operations with small effort requirements (1-4 hours each). All 5 operations are independent and can be implemented in parallel by different developers or in any order.

## Operations in This Phase

1. **Sample** (2-3h) - `./01-sample.md`
2. **Head/Tail/Limit** (2-3h) - `./02-limit.md`
3. **Top K / Bottom K** (3-4h) - `./03-topk.md`
4. **Null Count** (2h) - `./04-null-count.md`
5. **Value Counts** (3-4h) - `./05-value-counts.md`

## Parallelization Strategy

### Option A: 5 Developers (Optimal)
- Dev 1: Sample
- Dev 2: Limit
- Dev 3: Top K
- Dev 4: Null Count
- Dev 5: Value Counts

**Timeline**: 3-4 hours (one sitting)

### Option B: 2 Developers
- Dev 1: Sample + Top K (5-7h)
- Dev 2: Limit + Null Count + Value Counts (7-9h)

**Timeline**: 7-9 hours

### Option C: 1 Developer
Do in order of value:
1. Sample
2. Limit
3. Top K
4. Value Counts
5. Null Count

**Timeline**: 12-16 hours

## Common Implementation Pattern

All operations follow the same pattern:

### Backend (`backend/modules/compute/engine.py`)
1. Add operation case to `_apply_step` method
2. Parse parameters
3. Call Polars method
4. Return result

### Frontend (`frontend/src/lib/components/operations/`)
1. Create config component (e.g., `SampleConfig.svelte`)
2. Use Svelte 5 runes (`$state`, `$derived`)
3. Minimal UI, match existing operation style
4. Export from `index.ts`

### Integration
1. Add to operation enum in backend schemas
2. Update `StepLibrary.svelte` to show in palette
3. Add schema calculation in `transformation-rules.ts`
4. Write backend tests (3-5 tests per operation)
5. Write component tests

## Testing Requirements

Each operation needs:
- Backend unit tests (3-5 tests)
  - Basic functionality test
  - Parameter validation test
  - Edge case test (empty dataframe, etc.)
- Frontend component tests
  - Config rendering
  - User interaction
  - State management

## Definition of Done

For each operation:
- [ ] Backend implementation in `engine.py`
- [ ] Frontend config component created
- [ ] Component exported in `index.ts`
- [ ] Added to `StepLibrary.svelte`
- [ ] Schema calculation added
- [ ] Backend tests written and passing
- [ ] Component tests written
- [ ] No LSP errors
- [ ] Manually tested in UI

## Dependencies

**None** - All operations are independent and can start immediately.

## Notes

- These are the fastest ROI operations
- All are commonly used in data analysis
- Simple UI requirements
- Low complexity, low risk
- Great for onboarding new contributors
- Can be done in a single sprint
