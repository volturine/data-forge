# Performance Baseline

## Purpose
Establish a repeatable baseline for backend pipeline performance so regressions can be detected early and performance work has a reference point.

## Environment
- Hardware: local dev machine
- OS: Linux
- Database: SQLite (default)
- Dataset: `backend/tests/fixtures/sample.csv`
- Build: local dev (no Docker)

## Baseline Steps

1. Install dependencies
   ```bash
   just install
   ```

2. Run backend tests to ensure a clean baseline
   ```bash
   just test
   ```

3. Run the performance test module
   ```bash
   cd backend
   uv run pytest tests/test_performance_baseline.py -q
   ```

## Metrics Captured
- `preview_duration_ms`
- `schema_duration_ms`
- `export_duration_ms`
- Row counts for preview/export

## Expected Output
The test prints a single JSON line with timing metrics, example:
```
{"preview_duration_ms": 123, "schema_duration_ms": 45, "export_duration_ms": 210, "preview_rows": 100, "export_rows": 1000}
```

## Notes
- Run the baseline on an idle machine for consistency.
- Keep the dataset constant; changes require re-baselining.
