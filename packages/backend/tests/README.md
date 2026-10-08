# Backend tests

Run backend unit tests through the isolated project recipe:

```bash
just test-backend-unit
```

## Persisted pipeline configurations

`fixtures/legacy_pipelines/` contains append-only pipeline snapshots organized by release or schema epoch. Keep existing snapshots unchanged; add a new file when a release or schema epoch adds step types or changes saved configs. The regression test requires fixtures to cover every step in `get_step_catalog()` and validates each saved config through both the API and protocol normalizers.

When a schema change renames or removes a field used in persisted pipeline configs, ship an Alembic data migration for both `analyses` and `analysis_versions`, then add a new legacy fixture. `0024_pivot_value_columns.py` is the migration pattern for rewriting stored step configs.

The fixture test discovers Alembic migrations in revision-file order and applies each public `rewrite_pipeline_definition(pipeline_definition, *, downgrade)` hook with `downgrade=False`. A future migration that rewrites persisted pipeline configs must expose that pure in-memory hook, so the fixture set is checked against every rewrite up to head. The v0.4.0 snapshot keeps the old pivot `values` key; without the #0024 hook the test reports the `pivot` step and `values` key that failed.
