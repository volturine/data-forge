# Task Tracker

## Status:

- [x] Fix analysis output branch defaults + branch creation in OutputNode
- [ ] Fix branch export metadata lookup (branch-specific tables + filter empty branches)
- [ ] Move namespace storage under DATA_DIR/namespaces/ and harden test isolation
- [ ] Fix datasource upload/ingest + branch UI regressions (CSV delimiter, Excel preflight, branch defaults, build logs, hidden toggle)
  - [x] Upload UI: upload-only file tab with CSV options and Excel preflight fixes
  - [x] Enforce single file type per bulk upload (frontend + backend)
  - [x] Iceberg add: root path only, remove branch input (frontend + backend)
  - [x] Namespace picker anchored to header trigger
  - [x] Branch picker width/z-index popover behavior
  - [x] Build logs show datasource create/update kinds
  - [x] Restore output hidden toggle and compact first row layout
  - [x] Datasources page defaults to master branch and branch list includes master
  - [ ] Re-ingest uploads on CSV/Excel config change
- [x] Adjust analysis node behavior: auto-apply inline view steps at 100 rows, chart nodes require apply with placeholder
- [x] Fix analysis save refresh + derived tab previews before save
- [x] Unify analysis DAG across tabs and restore default view nodes on new analysis
- [x] Make derived tabs behave like same-flow nodes (schema + datasource label + selection)
- [x] Use shared datasource selector for change mode + refresh previews without save
- [x] Fix drag/drop after derived tab creation (active tab switch)
- [x] Reuse existing output datasource on build (stable output IDs)
- [x] Generate output datasource IDs at tab creation (UUID stored in analysis config)
- [x] Document OpenCode subagents and skills lists in AGENTS.md
- [x] Follow-up: tweak OpenCode subagents note, fix Docs agent label, trim slash commands
- [x] Fix snapshot compare unique_count to ignore nulls
- [x] Update monitoring/builds/datasources preview toggles + snapshot mapping reuse
- [x] Datasources runs preview toggle + comparison toggle + bugs.md restore
- [x] Update datasources compare layout + snapshot filtering + monitoring toggle placement
- [x] Fix Iceberg export warehouse path to align with exports dir
- [x] Use per-output Iceberg catalog.db for exports
- [x] Branch-aware export path layout (master default)
- [x] Test isolation for exports directory
- [x] Branch-aware metadata path resolution and UI selection
- [x] Namespace picker modal + branch pickers (searchable, no free-text)

### Critical

- [x] 1. Compute engine job tracking race condition
- [x] 2. Compute engine env var pollution
- [x] 3. Analysis service missing transaction rollback
- [x] 4. Locks acquisition race condition
- [x] 7. Deterministic sample without seed
- [x] 8. Upload storage quota enforcement
- [x] Scheduling UX/validation fixes (raw datasets, schedule types, table UX)
- [x] Excel upload range selection (end-to-end)
  - [x] Backend parse/validate cell ranges with sheet handling
  - [x] Preflight/preview return sheet name + tests
  - [x] Confirm stores cell ranges/end row
  - [x] Frontend manual range input + end row in upload/config/preview
  - [x] Run svelte-autofixer on updated Svelte files
  - [x] just verify
- [x] Datasource type registry/category (enum, handlers, unsupported type guard)
- [x] Build comparison moves to datasources + dataset diff/mapping
  - [x] Move comparison UI into datasources tab
  - [x] Add metadata + dataset side-by-side diff with column mapping
  - [x] Trim builds page after move
- [x] Healthcheck criticals + new checks + row_count uniqueness
- [x] Verification steps (pre-write critical checks)

### High Priority

- [x] 11. Non-atomic analysis version increment
- [x] 12. Dirty reads during schema cache population
- [x] 15. Silent schema extraction failures
- [x] 16. Partial upload cleanup on failure
- [x] 17. Preflight files TTL cleanup
- [x] 18. Notification failures surfaced
- [x] 1. UUID format validation on routes
- [x] 2. API datasource URL validation
- [x] 23. Unescaped filename in HTTP header
- [x] 24. DuckDB temp cleanup on exception
- [x] 25. Iceberg path symlink defense
- [x] 26. File format validation via magic numbers
- [x] 27. ETag/version headers for concurrency
- [x] 28. Draft restore validation vs server
- [x] 29. Join schema empty fallback handling
- [x] 30. Schema refresh delay
- [x] 31. Locks module tests
- [x] 32. Engine runs module tests
- [x] 33. Analysis versions tests
- [x] 34. Frontend unit tests coverage
- [x] 35. Performance tests baseline
- [x] 36. Disabled steps passthrough + output notifications
- [x] 37. Export datasets use uuid paths + schema evolution
- [x] 59. Build query plan includes pre-eager steps annotation
- [x] 60. AI/notification steps remain lazy (no internal collect)
- [x] 61. Test DB isolation (prevent tests from touching production DB)
- [x] 62. Unified compute requests with full analysis payload
- [x] 63. Backend compute preview/schema/export accept analysis_pipeline + tab_id
- [x] 64. Build payload endpoint added and wired for OutputNode
- [x] 65. Remove legacy compute endpoints and payload fallbacks

### Medium Priority

- [x] Monitoring page tabs + compact health checks reuse
- [x] Monitoring page global search across builds/schedules/health checks

### Redesign

- [x] Data handling redesign (namespace + branch aware, DATA_DIR, per-namespace DBs)
  - [x] Plan:
    - [x] Backend: namespace-aware scheduler loop + per-namespace DB init/migrations + settings DB only
  - [x] Backend: datasource ingestion redesign (upload -> iceberg clean, existing iceberg validation, external DB ingest + refresh)
    - [x] Backend: output export branch support + remove hardcoded exports namespace defaults
  - [x] Frontend: datasource creation UI (3 strategies) + output branch config + lineage filter
  - [x] Docs/tests/env: remove legacy upload/clean/exports vars, update DATA_DIR references
  - [x] Update Dockerfile/test fixtures for namespace data paths
  - [x] Switch to DATA_DIR/app.db settings DB, namespace.db per namespace
  - [x] Namespace-aware schedules/builds/healthchecks stored in namespace.db
  - [x] Datasource creation strategies (upload -> iceberg clean, existing iceberg, external DB ingest + refresh)
  - [x] Frontend namespace selector label (analysis/namespace) + branch selection in outputs
  - [x] Update docs/tests/env for DATA_DIR, remove legacy upload/clean/exports vars

- [x] Iceberg snapshot comparison endpoint + build snapshot metadata + UI refresh
- [x] Rework snapshot comparison stats into unified table with deltas
- [x] Iceberg build mode: recreate (drop + create) support
- [x] Iceberg snapshot selection deterministic (no fallback mapping)
- [x] Iceberg output metadata_path uses latest metadata.json after recreate
- [x] Iceberg snapshot preview uses pyiceberg reader to avoid schema mismatch panic
- [x] Iceberg snapshot preview inserts missing columns to avoid failures
- [x] Ensure analysis pipeline always includes all tab datasource configs (lazyframe reuse)
- [x] Lazyframe upstream tab build ordering for payload builds
- [x] Analysis save should not create datasource rows (outputs created on build)
- [x] Update output datasource tests for new allocation behavior
- [x] Output node avoids querying virtual output datasources before build

- [x] 41. Remove hardcoded CORS IPs
- [x] 42. Disable public IDB debug by default
- [x] 43. Encrypt SMTP passwords at rest
- [x] 44. Validate database URL
- [x] 45. Normalize DELETE status codes
- [x] 46. Telegram settings unified + notifications gating
- [x] 47. Notification UDF recipient source selection
- [x] 51. Remove bare except clauses
- [x] 52. Preserve error context in exceptions
- [x] 53. Standardize error handling patterns
- [x] 54. User-friendly error messages
- [x] 55. Timeout handling consistency
- [x] 56. Process lifecycle gaps
- [x] 57. Check-then-act cleanup races
- [x] 58. Queue reuse after corruption timeout
