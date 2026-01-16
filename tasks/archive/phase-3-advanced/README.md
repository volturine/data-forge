# Phase 3 - Advanced Analytics

**Status**: Planning
**Total Estimated Effort**: 10-12 hours
**Priority**: High
**Parallelization**: Single operation, can be split into subtasks

## Overview

This phase contains the "Add Columns / With Columns" operation - the most complex and powerful operation for creating calculated fields.

## Operation in This Phase

1. **Add Columns / With Columns** (10-12h) - `./01-add-columns.md`

## Why This Is Its Own Phase

This operation is:
- **High complexity**: Multiple expression types (literal, arithmetic, concat, column copy)
- **High value**: Enables calculated fields, business logic, derived metrics
- **Large scope**: Complex UI builder, expression parser, type inference
- **User-facing**: Needs excellent UX to be accessible

## Parallelization Strategy

### Option A: 3 Developers (Optimal)
Split by expression type:
- Dev 1: Backend + Literal/Column copy (3-4h)
- Dev 2: Arithmetic expressions (3-4h)
- Dev 3: String concatenation + UI integration (4-5h)

**Timeline**: 4-5 hours with coordination

### Option B: 2 Developers
- Dev 1: Backend + Literal/Column/Arithmetic (6-7h)
- Dev 2: Concatenation + Full UI + Integration (6-7h)

**Timeline**: 6-7 hours

### Option C: 1 Developer
Full implementation in phases:
1. Backend structure + Literal expressions (3h)
2. Arithmetic expressions (3h)
3. Concatenation (2h)
4. UI builder (3h)
5. Integration + testing (2h)

**Timeline**: 10-12 hours (2 days)

## Key Features

- **Multiple Expression Types**:
  - Literal: Add constant value column
  - Column: Copy/rename column
  - Arithmetic: Math operations (+, -, *, /, %, **)
  - Concat: String concatenation

- **Visual Expression Builder**:
  - Add/remove column definitions
  - Type selection per column
  - Dynamic form based on type
  - Validation and preview

- **Type Inference**:
  - Determine output type from expression
  - Handle mixed types
  - Validation before execution

## Technical Challenges

1. **Expression Parsing**
   - Multiple expression types
   - Handling column references vs literals
   - Type coercion

2. **UI Complexity**
   - Dynamic forms
   - Multiple column definitions
   - Expression builder UX

3. **Schema Calculation**
   - Infer types from expressions
   - Handle arithmetic type promotion
   - String concatenation always returns String

4. **Error Handling**
   - Type mismatches
   - Invalid column references
   - Division by zero

## Testing Requirements

- 10+ backend tests covering:
  - Each expression type
  - Multiple columns at once
  - Type coercion
  - Error cases
  - Edge cases

- 3-4 frontend tests:
  - Adding/removing columns
  - Type switching
  - Validation

## Definition of Done

- [ ] All 4 expression types working
- [ ] Visual expression builder complete
- [ ] Schema calculation with type inference
- [ ] Comprehensive error handling
- [ ] All tests passing
- [ ] Documentation with examples
- [ ] Manual testing of common use cases

## Success Criteria

Users should be able to:
- Calculate profit = revenue - cost
- Create full_name = first_name + " " + last_name
- Convert units (celsius * 9/5 + 32)
- Add constant columns (status = "active")
- All without writing code

## Dependencies

**None** - Can start after Phase 1 or Phase 2, or in parallel.

**Recommendation**: Complete Phase 1 first to establish patterns, then tackle this.

## Future Enhancements

After initial implementation, consider:
- Conditional expressions (when/then)
- Function calls (abs, round, etc.)
- Date arithmetic
- Null handling options
- Expression templates/presets

## Notes

- This is the most valuable single operation
- Replaces need for many simple custom operations
- Good UX is critical for adoption
- Consider progressive disclosure (start simple, add advanced)
- Test thoroughly with real-world use cases
