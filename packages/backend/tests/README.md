# Backend tests

Run backend unit tests through the isolated project recipe:

```bash
just test-backend-unit
```

## Persisted pipeline configurations

`fixtures/legacy_pipelines/` contains append-only pipeline snapshots organized by release or schema epoch. Keep existing snapshots unchanged; add a new file when a release or schema epoch adds step types or changes saved configs. The regression test requires fixtures to cover every step in `get_step_catalog()` and validates each saved config through both the API and protocol normalizers.

When a schema change renames or removes a field used in persisted pipeline configs, ship an Alembic data migration for both `analyses` and `analysis_versions`, then add a new legacy fixture. `0024_pivot_value_columns.py` is the migration pattern for rewriting stored step configs. The v0.4.0 snapshot keeps the old pivot `values` key so removing that migration makes the test report the `pivot` step and `values` key that failed.
