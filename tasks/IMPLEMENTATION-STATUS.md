# Implementation Status

Last Updated: 2026-01-16

## Operations Implementation Matrix

### Fully Implemented Operations (16)

| Operation | Backend Engine | Step Converter | Frontend Config | Schema Calculator | StepLibrary UI | Status |
|-----------|---------------|----------------|-----------------|-------------------|----------------|--------|
| filter | engine.py:236 | convert_filter_config | FilterConfig.svelte | applyFilterRule | Yes | COMPLETE |
| select | engine.py:292 | passthrough | SelectConfig.svelte | applySelectRule | Yes | COMPLETE |
| groupby | engine.py:296 | convert_groupby_config | GroupByConfig.svelte | applyGroupByRule | Yes | COMPLETE |
| sort | engine.py:318 | convert_sort_config | SortConfig.svelte | applySortRule | Yes | COMPLETE |
| rename | engine.py:328 | convert_rename_config | RenameConfig.svelte | applyRenameRule | Yes | COMPLETE |
| drop | engine.py:347 | passthrough | DropConfig.svelte | applyDropRule | Yes | COMPLETE |
| with_columns | engine.py:332 | passthrough | ExpressionConfig.svelte | applyExpressionRule | Yes (as expression) | COMPLETE |
| pivot | engine.py:351 | convert_pivot_config | PivotConfig.svelte | applyPivotRule | Yes | COMPLETE |
| timeseries | engine.py:359 | convert_timeseries_config | TimeSeriesConfig.svelte | applyTimeSeriesRule | Yes | COMPLETE |
| string_transform | engine.py:432 | convert_string_transform_config | StringMethodsConfig.svelte | applyStringTransformRule | Yes | COMPLETE |
| fill_null | engine.py:470 | convert_fillnull_config | FillNullConfig.svelte | applyFillNullRule | Yes | COMPLETE |
| deduplicate | engine.py:520 | convert_deduplicate_config | DeduplicateConfig.svelte | applyDeduplicateRule | Yes | COMPLETE |
| explode | engine.py:526 | passthrough | ExplodeConfig.svelte | applyExplodeRule | Yes | COMPLETE |
| view | engine.py:532 | passthrough | ViewConfig.svelte | applyViewRule | Yes | COMPLETE |
| unpivot | engine.py:537 | passthrough | - | applyUnpivotRule | No | BACKEND ONLY |
| join | engine.py:551 | convert_join_config | JoinConfig.svelte | applyJoinRule | Yes | PARTIAL* |

*Join is implemented as self-join only. Cross-datasource joins require architectural changes.

### Operations Needing Frontend Config

| Operation | Notes |
|-----------|-------|
| unpivot | Needs UnpivotConfig.svelte component and StepLibrary entry |

### Planned Operations (From Phase Tasks)

| Operation | Phase | Priority | Estimated Effort |
|-----------|-------|----------|------------------|
| sample | Phase 1 | High | 2-3 hours |
| limit | Phase 1 | High | 2-3 hours |
| topk | Phase 1 | High | 3-4 hours |
| null_count | Phase 1 | High | 2 hours |
| value_counts | Phase 1 | High | 3-4 hours |
| cast | Phase 2 | High | 5-7 hours |
| rank | Phase 2 | High | 4-5 hours |
| add_columns | Phase 3 | High | 10-12 hours |
| transpose | Phase 4 | Medium | 4-5 hours |
| when_then | Phase 5 | Medium | 10-12 hours |
| vstack | Phase 5 | Low | 12-15 hours |
| interpolate | Phase 5 | Low | 4-5 hours |
| sql | Phase 5 | Low | 6-8 hours |

## Recent Fixes (2026-01-16)

### Config Format Mismatches Fixed

1. **Rename Operation**: Frontend sends `column_mapping`, backend now accepts both `column_mapping` and `mapping`
2. **Sort Operation**: Frontend sends array `[{column, descending}]`, converter now transforms to `{columns: [], descending: []}`
3. **Pivot Operation**: Now accepts both `aggregate_function` (snake_case) and `aggregateFunction` (camelCase)
4. **Join Operation**: Now accepts both `left_on`/`right_on` (snake_case) and `leftOn`/`rightOn` (camelCase)

### New Implementations

1. **Unpivot**: Added to backend engine (melt/unpivot transformation)
2. **Join**: Added self-join support with clear error for cross-datasource joins
3. **Schema Calculator**: Added transformation rules for all operations

### UI Improvements

1. **StepLibrary**: Added 6 previously hidden operations to the UI palette:
   - Pivot
   - Fill Null
   - Deduplicate
   - Explode
   - Time Series
   - String Transform

## Architecture Notes

### Multi-Datasource Support (Future)

The current architecture supports linking multiple datasources to an analysis via the `AnalysisDataSource` junction table, but the compute engine only processes one datasource at a time.

For cross-datasource joins to work, we need:
1. Modify `execute_analysis` to accept multiple datasource IDs
2. Load multiple dataframes in the engine
3. Pass datasource references through pipeline steps
4. Implement proper join logic with second datasource

This is tracked in Phase 5 (vstack operation) which requires similar multi-dataframe architecture.

## File Reference

### Backend
- `backend/modules/compute/engine.py` - Operation implementations
- `backend/modules/compute/step_converter.py` - Frontend→Backend config conversion
- `backend/modules/compute/service.py` - Compute service layer
- `backend/modules/compute/routes.py` - API endpoints

### Frontend
- `frontend/src/lib/components/operations/*.svelte` - Operation config UIs
- `frontend/src/lib/components/pipeline/StepConfig.svelte` - Config orchestrator
- `frontend/src/lib/components/pipeline/StepLibrary.svelte` - Operation palette
- `frontend/src/lib/utils/schema/transformation-rules.ts` - Schema transformation rules
- `frontend/src/lib/utils/schema/schema-calculator.svelte.ts` - Schema calculator

## Testing

### Backend Tests
```bash
cd backend && uv run pytest -v
```

### Frontend Type Check
```bash
cd frontend && npm run check
```

### Frontend Build
```bash
cd frontend && npm run build
```
