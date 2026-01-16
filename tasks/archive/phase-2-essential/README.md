# Phase 2 - Essential Operations

**Status**: Ready to Start
**Total Estimated Effort**: 18-22 hours
**Priority**: High
**Parallelization**: All tasks can be done concurrently

## Overview

High-priority operations with medium effort (4-7 hours each). These are essential for data transformation workflows. All 4 operations are independent.

## Operations in This Phase

1. **Unpivot/Melt** (4-6h) - `./01-unpivot.md`
2. **Cast (Type Conversion)** (5-7h) - `./02-cast.md`
3. **Rank** (4-5h) - `./03-rank.md`

## Parallelization Strategy

### Option A: 3 Developers (Optimal)
- Dev 1: Unpivot (4-6h)
- Dev 2: Cast (5-7h)
- Dev 3: Rank (4-5h)

**Timeline**: 5-7 hours (one day)

### Option B: 2 Developers
- Dev 1: Unpivot + Rank (8-11h)
- Dev 2: Cast (5-7h)

**Timeline**: 8-11 hours

### Option C: 1 Developer
Do in order of value:
1. Cast (type conversion is fundamental)
2. Unpivot (inverse of pivot, high value)
3. Rank (analytics essential)

**Timeline**: 18-22 hours (2-3 days)

## Key Features

### Unpivot/Melt
- Inverse of Pivot operation
- Transform wide to long format
- Critical for data visualization prep
- Multi-column selection UI

### Cast
- Type conversion between data types
- Fix CSV import issues
- Enable numeric operations
- Validation and error handling critical

### Rank
- Ranking/percentile calculations
- Multiple ranking methods
- Top-N analysis enabler
- Adds new column with ranks

## Common Challenges

1. **Schema Calculation**
   - Cast: Updates column types
   - Unpivot: Transforms schema structure significantly
   - Rank: Adds new Int64 column

2. **UI Complexity**
   - Cast: Multi-column configuration
   - Unpivot: Multiple column selectors
   - Rank: Method selection + column naming

3. **Error Handling**
   - Cast: Invalid type conversions
   - Unpivot: Schema validation
   - Rank: Column selection validation

## Testing Requirements

Each operation needs:
- 5-7 backend tests (more complex than Phase 1)
- 2-3 frontend component tests
- Manual integration testing
- Edge case coverage

## Definition of Done

For each operation:
- [ ] Backend implementation complete
- [ ] Frontend config component with proper validation
- [ ] Schema calculation logic working
- [ ] All tests passing
- [ ] Error handling implemented
- [ ] Manually tested in UI
- [ ] Documentation updated

## Dependencies

**None** - All operations are independent.

Can start immediately after Phase 1 or in parallel with Phase 1.

## Notes

- These operations have more complex UIs than Phase 1
- Cast is particularly important for data cleaning
- Unpivot complements existing Pivot operation
- Rank enables many analytics use cases
- Consider user feedback from Phase 1 for UI patterns
