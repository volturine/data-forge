# Key Learnings

Project-specific gotchas and lessons discovered during development. **Read before working on related areas.**

## Svelte / Frontend

- **SvelteSet/SvelteMap are already reactive.** Never wrap in `$state()`. Use `const selected = new SvelteSet<T>()` directly. eslint `svelte/no-unnecessary-state-wrap` catches this.
- **transition-all Bloat.** Narrow to specific properties — `transition-all` forces tracking every CSS property across 1000+ elements.
- **CSS Paint Isolation.** `contain: content` on embedded scroll containers + `content-visibility: auto` on repeated items.
- **CSS `isolation: isolate`.** Use on canvas containers to scope child stacking contexts. Prevents CSS `transform` from creating new stacking contexts that paint over higher z-index siblings.
- **HTML Input Null-to-Empty Coercion.** HTML `<input>` elements convert `null` bound values to `""`, mutating config and triggering reactive loops. Default string fields in config to `''` not `null` in `step-config-defaults.ts`.
- **TanStack QueryKey Stability.** Never include mutable config values (e.g., `endpoint_url`, `api_key`) in queryKeys — they change during initialization, causing infinite refetch loops. Use only stable identifiers like `provider`.
- **Svelte component prop types.** When a config component uses a specific typed interface (e.g., `NotificationConfigData`), use that type in the `Props` interface — not `Record<string, unknown>`. Parent components cast with `as unknown as SpecificType`.
- **Width attributes.** Use Svelte actions, not attributes (causes check errors).
- **Inline Style Exception.** Keep inline `style=` for drag previews that require runtime mouse-following.
- **Config guards.** Config arrays like `input_columns` must be normalized before `.length` access to avoid UI crashes on initial render.
- **Number Input Cursor.** Use `oninput` without immediate coercion, coerce to number on `onblur` to prevent cursor jumping.

## Python / Backend

- **SQLite Naive Datetimes.** Always normalize to naive UTC before comparison. `datetime.now(UTC).replace(tzinfo=None)` for storage.
- **Pydantic Field Validators.** Use `field_validator` for type coercion (e.g., JSON string → dict) instead of fixing every caller.
- **Pydantic `exclude_unset` vs `exclude_none`.** Use `model_dump(exclude_unset=True)` for PATCH/update endpoints — `exclude_none=True` silently drops intentional `null` values.
- **DB Migrations.** `init_db()` uses `create_all()` which won't add columns to existing tables — use `_run_migrations()` with `ALTER TABLE` for new columns.
- **Cross-session DB test isolation.** When testing handlers that use `run_db()` (separate session), call `test_db_session.expire_all()` before asserting state changed by the handler.
- **FastAPI route ordering.** Parameterized routes like `/{run_id}` must come AFTER literal routes like `/compare`.
- **SQLModel `.where()` mypy.** All `.where(Model.field == value)` clauses need `# type: ignore[arg-type]` for mypy. For `bool` fields also add `# noqa: E712`.
- **Mypy `var-annotated` on dict literals.** When assigning a dict literal inside a branch, mypy requires an explicit type annotation. Use `object` as the value type for mixed-value dicts.
- **Mypy `call-overload` vs `arg-type`.** When `int(val)` is called on `object` type, mypy reports `call-overload` not `arg-type`. Use `# type: ignore[call-overload]`.
- **`Mapping` vs `dict` in function params.** When a function only reads from a dict, use `Mapping[K, V]` to accept covariant subtypes.
- **Ruff SIM102.** Never nest `if` statements when they can be combined with `and`.

## Architecture

- **`source_type` vs `created_by` semantics.** `source_type` = actual data format (`iceberg`, `csv`, `parquet`, etc.). `created_by` = origin (`analysis` for pipeline-built, `import` for file uploads). INPUT datasources referencing another analysis keep `source_type='analysis'` because the engine dispatches to `_load_analysis()` based on it. OUTPUT datasources use `source_type='iceberg'` from creation.
- **`output_datasource_id` architecture.** `datasource_id` on a tab is the INPUT source only. `output_datasource_id` is a separate field pointing to the hidden output datasource auto-created by `update_analysis()`. `_upsert_output_datasource()` is the DRY helper for all export paths.
- **Chart/View Nodes.** Pass-through — they do NOT modify the DAG. They take input data, visualize it, and let downstream steps see the same data.
- **AI Handler Architecture.** The AI node is a UDF wrapper for LLM chat APIs — NOT a general-purpose AI assistant. `AIParams` supports `input_columns: list[str]` (multi-column) with backward compat for legacy `input_column` via `model_validator`. Prompt templates use `{{column_name}}` placeholders. The handler runs in an engine subprocess — sync HTTP calls are fine.
- **Cross-Tab Invalidation.** When modifying steps in tab A, also mark view steps in dependent tabs for re-run.
- **Schedule Execution.** `run_analysis_build()` must execute ALL tabs — tabs with output config use `export_data()`, tabs without output but with `datasource_id` use `preview_step()` + notifications. Never skip tabs without export config.
- **Iceberg Export.** Use `table.overwrite(df)` for existing tables to replace data in a single snapshot.
- **Telegram Bot Architecture.** `TelegramBot` singleton does long-polling via `getUpdates` in background thread. Bot auto-starts on app startup if token is configured. Subscribers stored in DB, not env vars.
- **Schedule Dependencies.** `depends_on` field on `Schedule` model references another schedule ID. Scheduler loop does topological sort within each analysis's due schedules.
- **EngineRun `triggered_by`.** Distinguishes schedule-triggered vs user-triggered builds. Pass through `export_data()` and `preview_step()`.
- **Backend-generated fields should be optional in frontend types.** When the backend auto-creates/fills a field on save, make it optional (`?`) in the TypeScript interface.

## UI Patterns

- **Border consistency.** Use `border-tertiary` everywhere in tables.
- **Nested buttons.** Replace tab containers with `<div>` + separate buttons.
- **Config defaults.** Centralize defaults at creation in `step-config-defaults.ts`, not in components.
- **Column Dropdown Width.** Set `.column-menu` to `min-width: 100%; width: 100%; max-width: 100%;` to match trigger field width.
- **Svelte Action-Based Positioning.** Use Svelte actions to set CSS variables on portal elements for dynamic positioning.
