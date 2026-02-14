# Task Tracker

## Status: All bugs from `docs/bugs.md` resolved — `just verify` passes clean

**Last verified:** 316 backend tests passed, 0 failed. mypy: 0 issues. svelte-check: 0 errors, 0 warnings. eslint: 0 errors, 0 warnings. prettier: clean. ruff: clean.

---

## Completed — Phase 1 (Backend Critical Fixes + Frontend Fixes)

| # | Task | Files Changed |
|---|------|---------------|
| 1.1 | Fixed `EngineRunResponseSchema.progress` — `progress: float = 0.0` | `engine_runs/schemas.py` |
| 1.2 | Removed broken filter heuristic validation | `compute/engine.py` |
| 1.3 | Implemented `ChartHandler` — aggregation for 6 chart types | `compute/operations/plot.py` |
| 1.4 | Implemented `NotificationHandler` — validates preview, sends post-export | `compute/operations/notification.py`, `compute/service.py` |
| 1.5 | Fixed LineageGraph infinite `$effect` loop — plain Map for physics | `LineageGraph.svelte` |
| 1.6 | Created `ChartPreview.svelte` with Chart.js, wired into `StepNode.svelte` | `ChartPreview.svelte`, `StepNode.svelte` |
| 1.7 | Added healthcheck count badge | `DatasourceConfigPanel.svelte` |
| 1.8 | Created `SettingsPopup.svelte` — global SMTP/Telegram config | `SettingsPopup.svelte`, `+layout.svelte` |
| 1.9 | 30 backend tests in `test_fixes.py` | `tests/test_fixes.py` |

## Completed — Phase 2 (AI Node Improvements)

| # | Task | Files Changed |
|---|------|---------------|
| 2.1 | Replaced `requests` with `httpx` — retry logic, connection pooling, `AIError` | `ai/service.py` |
| 2.2 | AI error handling per batch — writes `[error: ...]` instead of crashing pipeline | `compute/operations/ai.py` |
| 2.3 | Fixed `request_options` type mismatch — `field_validator` on `AIParams` | `compute/operations/ai.py`, `ai/service.py` |
| 2.4 | Created `ai/routes.py` — `GET /models`, `GET /test` | `ai/routes.py`, `api/v1/router.py` |
| 2.5 | Created `ai.ts` API client — `listAIModels()`, `testAIConnection()` | `lib/api/ai.ts` |
| 2.6 | Rewrote `AIConfig.svelte` — schema prop, dynamic model loading, test button | `AIConfig.svelte`, `StepConfig.svelte` |
| 2.7 | 56 AI backend tests | `tests/test_ai.py` |

## Completed — Phase 3 (Column Stats, Version History, Builds UI)

| # | Task | Files Changed |
|---|------|---------------|
| 3.1 | Column stats: median, q25, q75 display | `ColumnStatsPanel.svelte` |
| 3.2 | Column stats: `onColumnStats` callback in DataTable | `DataTable.svelte`, `DatasourcePreview.svelte` |
| 3.3 | Version history: fixed imports, shared API functions | `analysis/[id]/+page.svelte`, `lib/api/analysis.ts` |
| 3.4 | Builds UI: rewrite with name resolution, waterfall, sorting, filters | `builds/+page.svelte` |

## Completed — Phase 4 (Scheduler)

| # | Task | Files Changed |
|---|------|---------------|
| 4.1 | `scheduler_check_interval` config | `core/config.py` |
| 4.2 | `get_due_schedules()`, `mark_schedule_run()`, `run_analysis_build()` | `scheduler/service.py` |
| 4.3 | `scheduler_loop()` async background task | `main.py` |
| 4.4 | Schedule API client + full management UI | `lib/api/schedule.ts`, `schedules/+page.svelte` |
| 4.5 | "Schedules" nav item with active state | `+layout.svelte` |
| 4.6 | 38 scheduler backend tests | `tests/test_scheduler.py` |
| 4.7 | Fixed SQLite naive datetime comparison in `should_run()` and `mark_schedule_run()` | `scheduler/service.py`, `tests/test_scheduler.py` |

## Completed — Phase 5 (Final Bug Fixes)

| # | Task | Files Changed |
|---|------|---------------|
| 5.1 | New tab defers datasource creation to save — removed eager `/datasource/connect` call | `analysis/[id]/+page.svelte` |
| 5.2 | Cross-tab preview invalidation — dependent tabs marked for re-run on source change | `stores/analysis.svelte.ts` |
| 5.3 | `buildAnalysisPipelinePayload` no longer bails on partially missing sources | `utils/analysis-pipeline.ts` |

## Dead Code Removed

| File | Lines | Reason |
|------|-------|--------|
| `IndexedDbDebugPanel.svelte` | 81 | Zero imports anywhere |
| `StatsPanel.svelte` | 111 | Superseded by `ColumnStatsPanel` |
| `.idb-debug-panel*` CSS | ~80 | Orphaned after component removal |

## Completed — Phase 6 (Lint Cleanup + Meta Updates)

| # | Task | Files Changed |
|---|------|---------------|
| 6.1 | Fixed ruff lint errors (F841, SIM102, SIM108, D209, D415, B017, I001, F401) | `engine.py`, `datasource.py`, `service.py`, `plot.py`, `notification.py`, `test_fixes.py`, `test_ai.py`, `test_scheduler.py` |
| 6.2 | Fixed mypy errors — Polars `PythonLiteral` type narrowing in histogram bins | `compute/operations/plot.py` |
| 6.3 | Fixed mypy error — SQLModel `Schedule.enabled` where clause typing | `scheduler/service.py` |
| 6.4 | Fixed ESLint error — removed unused `AnalysisVersion` type import | `analysis/[id]/+page.svelte` |
| 6.5 | Fixed ESLint warnings — `Map`/`Date` in non-reactive contexts with eslint-disable | `LineageGraph.svelte`, `ChartPreview.svelte`, `builds/+page.svelte` |
| 6.6 | Fixed svelte-check a11y warning — label association on ColumnDropdown | `AIConfig.svelte` |
| 6.7 | Updated `AGENTS.md` — behavioral rules, architecture docs, patterns | `AGENTS.md` |
| 6.8 | Updated `Justfile` — added `check`, `test`, `verify`, `lint-backend`, `lint-frontend` | `Justfile` |
| 6.9 | Updated `docs/taskfile.md` — comprehensive status tracking | `docs/taskfile.md` |
