# Phase 5 - Complex/Advanced Operations

**Status**: Future Work
**Total Estimated Effort**: 30-40 hours
**Priority**: Low to Medium
**Parallelization**: Limited (architectural changes required)

## Overview

Advanced operations that either require significant architectural changes or are lower priority. Some operations require multi-dataframe support.

## Operations in This Phase

1. **Conditional When/Then** (10-12h) - `./01-when-then.md`
2. **VStack (Concatenate Rows)** (12-15h) - `./02-vstack.md`
3. **Interpolate** (4-5h) - `./03-interpolate.md`
4. **SQL Query** (6-8h) - `./04-sql.md`

## Architectural Requirements

### Multi-DataFrame Support
Operations VStack and potential future Cross Join require:
- Pipeline step dependencies
- Reference to other datasources
- Multi-dataframe execution context
- Schema compatibility validation

This is a **significant architectural change** affecting:
- Pipeline execution engine
- UI for selecting source steps
- Schema calculation system
- State management

**Recommendation**: Design multi-dataframe architecture separately before implementing VStack.

## Parallelization Strategy

### Phase 5A: No Architectural Changes Required
Can be done in parallel:
- Dev 1: Conditional When/Then (10-12h)
- Dev 2: Interpolate (4-5h)
- Dev 3: SQL Query (6-8h)

**Timeline**: 10-12 hours

### Phase 5B: Architectural Changes Required
Must be done sequentially:
1. Design multi-dataframe architecture (8-10h)
2. Implement architecture changes (10-15h)
3. Implement VStack (4-6h) - now easier with architecture

**Timeline**: 22-31 hours over 3-4 days

### When to Start

- **Phase 5A**: After Phase 3 is complete
- **Phase 5B**: After all other phases complete AND user demand exists

## Operation Summaries

### Conditional When/Then (10-12h) - Phase 5A
Create columns with conditional logic (SQL CASE WHEN).

**Complexity**: High - condition parser, chain builder, UI complexity

**Value**: High - enables business logic without code

**Priority**: Medium-High

### VStack (12-15h) - Phase 5B
Append rows from another dataframe.

**Complexity**: Very High - requires architectural changes

**Value**: Medium - useful but not essential

**Priority**: Medium

**Blockers**: Requires multi-dataframe pipeline architecture

### Interpolate (4-5h) - Phase 5A
Fill missing values with interpolation.

**Complexity**: Medium - multiple interpolation methods

**Value**: Medium - useful for time-series

**Priority**: Medium

### SQL Query (6-8h) - Phase 5A
Run SQL queries on DataFrame.

**Complexity**: Medium-High - SQL parsing, error handling

**Value**: Medium - alternative interface for SQL users

**Priority**: Low-Medium

## Recommended Implementation Order

1. **First**: Conditional When/Then
   - High value, no architecture changes
   - Enables business logic rules
   - Complex but well-scoped

2. **Second**: Interpolate
   - Medium value, straightforward
   - Complements existing FillNull operation
   - Useful for time-series users

3. **Third**: SQL Query
   - Alternative interface
   - Useful for SQL-familiar users
   - Can reuse expression parsing if available

4. **Last**: VStack
   - Requires architecture changes
   - Assess user demand first
   - Consider if multi-dataframe support is worth the effort

## Multi-DataFrame Architecture Design

Before implementing VStack or Cross Join, design:

### Pipeline Changes
- Step dependencies: "This step uses output from Step X"
- Execution order validation
- Circular dependency detection

### UI Changes
- Step selector in operation config
- Visual dependency graph
- Clear error messages for invalid references

### Schema Calculation
- Access to multiple step schemas
- Validation of schema compatibility
- Update downstream steps when upstream changes

### State Management
- Track step relationships
- Handle step deletion (cascade updates)
- Undo/redo with dependencies

**Estimated Design + Implementation**: 18-25 hours

## Testing Requirements

### Phase 5A Operations
Each operation:
- 8-12 backend tests
- 3-4 component tests
- Complex scenario coverage
- Error handling validation

### Phase 5B (VStack)
- Architecture tests (5-10 tests)
- VStack operation tests (5-8 tests)
- Integration tests (3-5 tests)
- UI tests for step selection

## Definition of Done

### Phase 5A
For each operation:
- [ ] Backend implementation
- [ ] Complex UI builder
- [ ] Schema calculation
- [ ] Comprehensive tests
- [ ] Error handling
- [ ] Documentation with examples
- [ ] Manual testing

### Phase 5B
- [ ] Multi-dataframe architecture designed
- [ ] Architecture implementation complete
- [ ] Architecture tests passing
- [ ] VStack operation implemented
- [ ] Integration tested
- [ ] Documentation updated

## Success Metrics

### Conditional When/Then
Users can create:
- Status flags based on conditions
- Category assignments
- Calculated indicators
- All without code

### VStack
Users can:
- Combine monthly files
- Append new data to existing
- Union datasets

## Dependencies

**Phase 5A**: Can start after Phase 3

**Phase 5B**: Should start only after:
- Phases 1-3 complete
- User demand validated
- Resources available for architecture work

## Risk Assessment

### Conditional When/Then
- **Risk**: Medium - Complex UI, many edge cases
- **Mitigation**: Start simple, add features incrementally

### VStack
- **Risk**: High - Architecture changes affect entire system
- **Mitigation**: Thorough design phase, feature flag, gradual rollout

### Interpolate
- **Risk**: Low - Well-defined, limited scope
- **Mitigation**: Standard testing

### SQL Query
- **Risk**: Medium - SQL parsing complexity
- **Mitigation**: Use Polars SQL capabilities, limit scope

## Notes

- Phase 5A can provide significant value without architectural changes
- Phase 5B should be evaluated based on user demand
- Consider if Expression operation already covers some SQL use cases
- Conditional When/Then is highest priority in this phase
- Multi-dataframe architecture is a project unto itself
