# Tasks

This directory tracks implementation status and planned work for the Polars FastAPI Svelte data analysis platform.

## Current Status

See **[IMPLEMENTATION-STATUS.md](./IMPLEMENTATION-STATUS.md)** for:
- Complete operation implementation matrix (16 operations fully implemented)
- Recent fixes and improvements
- Planned operations roadmap
- File references and architecture notes

## Quick Reference

### Implemented Operations (16)
- **Core**: filter, select, groupby, sort, rename, drop
- **Reshape**: pivot, unpivot, explode
- **Clean**: fill_null, deduplicate
- **Compute**: with_columns (expression)
- **Text/Time**: string_transform, timeseries
- **Other**: view, join (self-join)

### Next Priority
1. Create UnpivotConfig.svelte frontend component
2. Phase 1 operations: sample, limit, topk, null_count, value_counts
3. Phase 2 operations: cast, rank

## Archive

Historical task documentation and planning files are in `./archive/`:
- Phase planning documents (phase-1 through phase-5)
- Original task specifications
- Migration notes
- Module-specific task breakdowns

## Contributing

When adding new operations, follow the pattern in IMPLEMENTATION-STATUS.md:
1. Backend: Add to `engine.py` `_apply_step` method
2. Converter: Add to `step_converter.py` if format conversion needed
3. Frontend: Create config component in `operations/`
4. Schema: Add transformation rule to `transformation-rules.ts`
5. Calculator: Register in `schema-calculator.svelte.ts`
6. UI: Add to `StepLibrary.svelte`
7. Update IMPLEMENTATION-STATUS.md
