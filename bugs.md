# Audit Findings And Fix Log

This document captures all findings identified during the repository audit on 2026-04-13.

Scope:
- Reviewed tracked source, config, test, migration, and workflow files.
- Excluded generated/vendor/runtime artifacts from substantive review.
- `just verify` now passes after the fixes in this document. Strengthening the gate exposed one additional websocket-shutdown regression, which was fixed during this pass.

Severity:
- `High`: likely correctness or user-facing behavior risk.
- `Medium`: important design/test/workflow issue with real regression risk.
- `Low`: maintainability, drift, or standards violation that should be fixed before it compounds.
- `Fixed`: implemented and verified in this pass.
- `Open`: intentionally left for a later pass; rationale noted inline.

## High

### 1. Analysis editor has uncancelled async effects that can apply stale state after navigation or source changes

- Status: `Fixed`
- Principle(s): `Think Before Coding`, `Goal-Driven Execution`
- Confidence: `Confirmed`
- Files:
  - [frontend/src/routes/analysis/[id]/+page.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/routes/analysis/[id]/+page.svelte:203)
  - [frontend/src/routes/analysis/[id]/+page.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/routes/analysis/[id]/+page.svelte:218)
  - [frontend/src/routes/analysis/[id]/+page.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/routes/analysis/[id]/+page.svelte:494)
  - [frontend/src/routes/analysis/[id]/+page.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/routes/analysis/[id]/+page.svelte:515)
  - [frontend/src/routes/analysis/[id]/+page.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/routes/analysis/[id]/+page.svelte:551)
- Detail:
  - IndexedDB draft hydration and schema-fetch effects update shared stores when promises resolve, but they do not verify that the analysis id, active tab, or schema key is still current.
  - Fast navigation, lock-state changes, tab switches, or datasource changes can let stale callbacks overwrite current editor state.
  - This is a real race condition, not just complexity.
- Fix log:
  - Added [frontend/src/lib/utils/async-gate.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/lib/utils/async-gate.ts:1) and [frontend/src/lib/utils/async-gate.test.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/lib/utils/async-gate.test.ts:1).
  - Guarded draft hydration, inferred-schema hydration, and source-schema loads in [frontend/src/routes/analysis/[id]/+page.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/routes/analysis/[id]/+page.svelte:102).

### 2. Datasource upload rewrites validation failures into generic 500 responses

- Status: `Fixed`
- Principle(s): `Think Before Coding`, `No hidden compromises`
- Confidence: `Confirmed`
- Files:
  - [backend/modules/datasource/routes.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/modules/datasource/routes.py:143)
  - [backend/modules/datasource/routes.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/modules/datasource/routes.py:154)
  - [backend/modules/datasource/service.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/modules/datasource/service.py:147)
  - [backend/modules/datasource/service.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/modules/datasource/service.py:172)
- Detail:
  - The route catches all exceptions from `create_file_datasource()` and always rethrows `HTTP 500`.
  - The service already distinguishes invalid input and ingestion validation problems from internal failures.
  - Result: user-correctable upload issues become opaque server errors, making both UI behavior and diagnosis worse.
- Fix log:
  - Preserved `AppError` and `ValueError` propagation in [backend/modules/datasource/routes.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/modules/datasource/routes.py:143).
  - Added regression coverage in [backend/tests/test_datasource.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/tests/test_datasource.py:98).

## Medium

### 3. Playwright coverage is heavily API-seeded, so much of the suite is not exercising real user setup flows

- Status: `Fixed`
- Principle(s): `Goal-Driven Execution`
- Confidence: `Confirmed`
- Files:
  - [frontend/tests/utils/api.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/utils/api.ts:43)
  - [frontend/tests/utils/api.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/utils/api.ts:176)
  - [frontend/tests/fixtures.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/fixtures.ts:29)
  - [frontend/tests/analysis-crud.test.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/analysis-crud.test.ts:21)
  - [AGENTS.md](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/AGENTS.md:121)
- Detail:
  - Worker auth is created directly through backend APIs.
  - Datasources, analyses, schedules, health checks, and UDFs are routinely created through helper APIs instead of the UI flows under test.
  - The repo already warns about this explicitly, but the suite still depends on it extensively.
- Fix log:
  - Made the suite’s hybrid nature explicit in [frontend/tests/README.md](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/README.md:1), [frontend/tests/utils/api.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/utils/api.ts:5), [frontend/tests/fixtures.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/fixtures.ts:30), and the `test:hybrid-e2e` alias in [frontend/package.json](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/package.json:19).

### 4. Settings writes can report success even when Telegram bot runtime state failed to update

- Status: `Fixed`
- Principle(s): `Think Before Coding`, `No hidden compromises`
- Confidence: `Confirmed`
- Files:
  - [backend/modules/settings/routes.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/modules/settings/routes.py:64)
  - [backend/modules/settings/routes.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/modules/settings/routes.py:69)
  - [backend/tests/test_telegram.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/tests/test_telegram.py:423)
- Detail:
  - After persisting settings, bot start/stop failures are swallowed and only logged.
  - The API can therefore return a successful settings write even when the runtime bot did not actually enter the requested state.
  - The existing tests cover the success path but do not appear to assert the failure semantics.
- Fix log:
  - Runtime application failures now surface as `502` in [backend/modules/settings/routes.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/modules/settings/routes.py:67).
  - Added assertions for start/stop/failure behavior in [backend/tests/test_telegram.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/tests/test_telegram.py:427).

### 5. Several settings endpoints do synchronous network/SMTP work despite the backend async rule

- Status: `Fixed`
- Principle(s): `Simplicity First`
- Confidence: `Confirmed`
- Files:
  - [AGENTS.md](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/AGENTS.md:87)
  - [backend/modules/settings/routes.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/modules/settings/routes.py:77)
  - [backend/modules/settings/routes.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/modules/settings/routes.py:103)
  - [backend/modules/settings/routes.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/modules/settings/routes.py:130)
- Detail:
  - `test_smtp`, `test_telegram`, and the Telegram chat-detection endpoints are sync handlers doing external I/O directly.
  - That drifts from the repo’s stated async FastAPI standard and increases the chance of request-thread blocking under load.
- Fix log:
  - Converted the blocking settings test/detection endpoints to `async` and pushed external I/O through `run_in_threadpool` in [backend/modules/settings/routes.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/modules/settings/routes.py:75).

### 6. StepConfig relies on a long chain of `as unknown as` casts instead of typed dispatch

- Status: `Fixed`
- Principle(s): `Simplicity First`
- Confidence: `Confirmed`
- Files:
  - [frontend/src/lib/components/pipeline/StepConfig.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/lib/components/pipeline/StepConfig.svelte:392)
  - [frontend/src/lib/components/pipeline/StepConfig.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/lib/components/pipeline/StepConfig.svelte:443)
  - [frontend/src/lib/components/pipeline/StepConfig.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/lib/components/pipeline/StepConfig.svelte:490)
- Detail:
  - The central config renderer bypasses type safety for almost every step type.
  - That means config-shape mismatches are deferred to runtime and makes the component harder to change safely.
  - It is also directly against the repo guidance to avoid casts unless strictly necessary.
- Fix log:
  - Replaced the template-wide `as unknown as` chain with typed getter/setter bind bridges in [frontend/src/lib/components/pipeline/StepConfig.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/lib/components/pipeline/StepConfig.svelte:88).

### 7. `just verify` does not include tests, so the required completion gate does not verify behavior

- Status: `Fixed`
- Principle(s): `Goal-Driven Execution`
- Confidence: `Confirmed`
- Files:
  - [Justfile](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/Justfile:67)
  - [Justfile](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/Justfile:75)
  - [Justfile](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/Justfile:76)
- Detail:
  - `test` exists and runs backend + frontend unit tests.
  - `verify` is only `format check`.
  - The repo instructions treat `just verify` as the hard completion gate, but today that gate does not exercise runtime behavior at all.
- Fix log:
  - Updated [Justfile](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/Justfile:76) so `verify` now runs `format`, `check`, and `test`.
  - The stronger gate immediately exposed and then verified the websocket close-race matcher fix in [backend/modules/compute/routes.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/modules/compute/routes.py:31).

### 8. MCP output-schema formatting logic is duplicated in backend and frontend, creating drift risk

- Status: `Fixed`
- Principle(s): `Simplicity First`, `Surgical Changes`
- Confidence: `Confirmed`
- Files:
  - [backend/modules/chat/tool_contract.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/modules/chat/tool_contract.py:8)
  - [backend/modules/chat/tool_contract.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/modules/chat/tool_contract.py:27)
  - [frontend/src/lib/components/common/ChatPanel.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/lib/components/common/ChatPanel.svelte:147)
  - [frontend/src/lib/components/common/ChatPanel.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/lib/components/common/ChatPanel.svelte:165)
  - [frontend/src/lib/components/common/ChatPanel.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/lib/components/common/ChatPanel.svelte:1107)
- Detail:
  - Both sides independently inspect output schemas and format hints/field lists.
  - That kind of duplication tends to drift when contract behavior changes.
  - It is a design smell, especially in an area the repo has already had schema-contract issues around.
- Fix log:
  - Centralized output-schema helpers in [backend/modules/mcp/tool_output.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/modules/mcp/tool_output.py:1).
  - Registry now emits precomputed `fields` and `hint` in [backend/modules/mcp/registry.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/modules/mcp/registry.py:98).
  - Frontend now consumes those fields directly in [frontend/src/lib/components/common/ChatPanel.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/lib/components/common/ChatPanel.svelte:147).

### 9. Playwright tests still rely on brittle `.first()` and global text matching patterns that AGENTS explicitly warns against

- Status: `Fixed`
- Principle(s): `Goal-Driven Execution`
- Confidence: `Confirmed`
- Files:
  - [AGENTS.md](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/AGENTS.md:112)
  - [frontend/tests/analysis-crud.test.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/analysis-crud.test.ts:49)
  - [frontend/tests/analysis-crud.test.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/analysis-crud.test.ts:65)
  - [frontend/tests/monitoring.test.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/monitoring.test.ts:119)
  - [frontend/tests/monitoring.test.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/monitoring.test.ts:149)
  - [frontend/tests/utils/analysis.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/utils/analysis.ts:32)
- Detail:
  - The suite still uses `.first()` on broad locators and row lookups driven by free text.
  - That is the exact class of selector brittleness the repo’s learnings section says to avoid.
  - These tests may be green now but remain fragile to layout/order changes.
- Fix log:
  - Improved the shared setup flow in [frontend/tests/utils/user-flows.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/utils/user-flows.ts:45).
  - Added schedule row data attributes in [frontend/src/lib/components/common/ScheduleManager.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/lib/components/common/ScheduleManager.svelte:1394) and updated the referenced monitoring tests in [frontend/tests/monitoring.test.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/monitoring.test.ts:115).
  - Replaced brittle gallery/editor helpers in [frontend/tests/analysis-crud.test.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/analysis-crud.test.ts:16) and [frontend/tests/utils/analysis.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/utils/analysis.ts:6).
  - Added stable health-check row attributes in [frontend/src/lib/components/common/HealthChecksManager.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/lib/components/common/HealthChecksManager.svelte:1177) and updated both [frontend/tests/monitoring.test.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/monitoring.test.ts:339) and [frontend/tests/utils/ui-cleanup.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/utils/ui-cleanup.ts:110).
  - Removed additional `.first()`-driven selectors from shared readiness helpers, locking flows, analysis editor specs, and schedule cleanup in [frontend/tests/utils/readiness.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/utils/readiness.ts:1), [frontend/tests/analysis-locking.test.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/analysis-locking.test.ts:63), [frontend/tests/analysis-editor.test.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/analysis-editor.test.ts:1), and [frontend/tests/utils/ui-cleanup.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/utils/ui-cleanup.ts:98).
  - Removed remaining `.first()` usage from the datasource and UDF management specs by switching to stable row/card-scoped assertions in [frontend/tests/datasources.test.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/datasources.test.ts:1) and [frontend/tests/udfs.test.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/udfs.test.ts:1).
  - Added stable output-node hooks in [frontend/src/lib/components/pipeline/OutputNode.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/lib/components/pipeline/OutputNode.svelte:632) and replaced the remaining broad output/build selectors in [frontend/tests/analysis-output.test.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/analysis-output.test.ts:18) and [frontend/tests/build-preview.test.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/build-preview.test.ts:39).
  - Removed more singleton `.first()` selectors from [frontend/tests/navigation.test.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/navigation.test.ts:63) and the early sort/rename/filter operation flows in [frontend/tests/analysis-operations.test.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/analysis-operations.test.ts:158).
  - Added stable build row and payload hooks in [frontend/src/lib/components/common/BuildsManager.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/lib/components/common/BuildsManager.svelte:718), [frontend/src/lib/components/common/BuildPreview.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/lib/components/common/BuildPreview.svelte:977), and [frontend/src/lib/components/common/ScheduleManager.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/lib/components/common/ScheduleManager.svelte:1581), then rewrote the remaining monitoring/build-history selectors in [frontend/tests/monitoring.test.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/monitoring.test.ts:97).
  - Added semantic group hooks in [frontend/src/lib/components/operations/JoinConfig.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/lib/components/operations/JoinConfig.svelte:255) and [frontend/src/lib/components/operations/PivotConfig.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/lib/components/operations/PivotConfig.svelte:39), then removed the remaining order-based operation selectors in [frontend/tests/analysis-operations.test.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/analysis-operations.test.ts:363).
  - Completed the residual singleton cleanup in [frontend/tests/analysis-crud.test.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/analysis-crud.test.ts:242), [frontend/tests/namespace-isolation.test.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/namespace-isolation.test.ts:49), [frontend/tests/lineage.test.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/lineage.test.ts:127), [frontend/tests/navigation.test.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/navigation.test.ts:64), [frontend/tests/utils/namespace.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/utils/namespace.ts:19), and [frontend/tests/utils/visual.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/utils/visual.ts:46).
  - Repo-wide selector sweep now shows no remaining `.first()` usage under `frontend/tests` or `frontend/tests/utils`.

## Low

### 10. ChartPreview hardcodes raw hex colors instead of design tokens

- Status: `Fixed`
- Principle(s): `Surgical Changes`
- Confidence: `Confirmed`
- Files:
  - [AGENTS.md](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/AGENTS.md:76)
  - [frontend/src/lib/components/pipeline/ChartPreview.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/lib/components/pipeline/ChartPreview.svelte:30)
- Detail:
  - The chart palette is hardcoded as raw hex values.
  - The repo’s styling rules say to use semantic color tokens rather than raw colors.
  - This is not an immediate bug, but it is direct standards drift in a shared UI primitive.
  - chart palette should be configurable by user from chart node config, but the basis should use tokens.
- Fix log:
  - Switched the built-in palette to CSS token variables in [frontend/src/lib/components/pipeline/ChartPreview.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/lib/components/pipeline/ChartPreview.svelte:30).

### 11. Several key modules have grown into oversized “god files”

- Status: `Open`
- Principle(s): `Simplicity First`
- Confidence: `Confirmed`
- Files:
  - [frontend/src/lib/components/pipeline/ChartPreview.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/lib/components/pipeline/ChartPreview.svelte:1)
  - [frontend/src/lib/components/common/ChatPanel.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/lib/components/common/ChatPanel.svelte:1)
  - [frontend/src/routes/analysis/[id]/+page.svelte](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/routes/analysis/[id]/+page.svelte:1)
  - [backend/modules/compute/service.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/modules/compute/service.py:2631)
- Detail:
  - Audit sizing showed:
    - `ChartPreview.svelte`: 4,275 lines
    - `ChatPanel.svelte`: 2,718 lines
    - `analysis/[id]/+page.svelte`: 1,882 lines
    - `compute/service.py`: 3,232 lines
    - `run_analysis_build_stream()` alone: 464 lines
  - These files exceed the point where localized reasoning stays cheap.
  - This is a maintainability finding, but it materially increases bug density and review difficulty.
- Fix log:
  - Not addressed in this pass. Splitting these files cleanly is a larger refactor that should be done feature-by-feature with dedicated regression coverage.

### 12. Telegram bot polling uses broad exception handling and sleep-based retry loops

- Status: `Fixed`
- Principle(s): `Think Before Coding`, `Simplicity First`
- Confidence: `Confirmed`
- Files:
  - [backend/modules/telegram/bot.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/modules/telegram/bot.py:74)
  - [backend/modules/telegram/bot.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/modules/telegram/bot.py:88)
  - [backend/modules/telegram/bot.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/modules/telegram/bot.py:104)
  - [backend/modules/telegram/bot.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/modules/telegram/bot.py:127)
- Detail:
  - The polling/runtime path previously handled many failures with broad `except Exception` and fixed `time.sleep()` backoff.
  - It runs in a background thread, so this is less severe than blocking request handlers, but it still makes shutdown and failure semantics less explicit than they should be.
- Fix log:
  - Tightened payload validation and removed the broad poll-loop catch-all in [backend/modules/telegram/bot.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/modules/telegram/bot.py:74).
  - Replaced fixed retry sleeps with stop-aware waits and narrowed send-message failure handling in [backend/modules/telegram/bot.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/modules/telegram/bot.py:74) with coverage in [backend/tests/test_telegram.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/tests/test_telegram.py:312).
  - Narrowed subscribe/unsubscribe command-path failures to `SQLAlchemyError` and added regression coverage in [backend/tests/test_telegram.py](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/tests/test_telegram.py:362).

## Notes

- This file records all findings identified during the audit. It is not a proof that no other issues exist.
- The highest-risk areas not expanded into additional individual findings were the very large compute and frontend orchestration files, because they already surfaced enough concrete defects to justify follow-up refactors.
