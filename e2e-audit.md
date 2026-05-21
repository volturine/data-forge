# E2E audit

Current policy:
- Playwright retries are forbidden (`retries: 0`)
- Product assertions should remain UI-visible and user-like
- Automation is acceptable only where UI/browser-only setup is impractical or impossible

## Accepted automation

### Auth bootstrap
Files:
- `packages/frontend/tests/fixtures.ts`

Why kept:
- Creating authenticated worker sessions from scratch for every test via UI would dominate suite time.
- This setup does not replace product assertions; it only prepares signed-in browser state.

### Opaque id capture after UI submits
Files:
- `packages/frontend/tests/utils/user-flows.ts`

Examples:
- `uploadDatasourceViaUi(...)` now uses the real upload UI, captures the created datasource id from the browser-observed upload response, and verifies the browser-visible `/datasources?created_id=...` redirect
- `createScheduleViaUi(...)`, `createHealthCheckViaUi(...)`, `createUdfViaUi(...)` still capture ids from the response after clicking the real UI submit controls

Why kept:
- Datasource creation now has a browser-visible id handoff.
- Some other create flows still do not expose created ids directly in the UI.
- Tests still perform the visible user action first; id capture is only used to retain machine identifiers for later setup.

### Imported analysis setup that needs datasource id remapping
Files:
- `packages/frontend/tests/utils/api.ts`
- `packages/frontend/tests/utils/user-flows.ts`

Why kept:
- The import flow is UI-driven, but imported pipeline remapping currently requires datasource ids.
- Without a browser-visible way to select remaps by a stable human-facing key alone, helper-level id plumbing remains necessary.

## Already migrated to UI

### Engine shutdown
Files:
- `packages/frontend/tests/utils/user-flows.ts`
- `packages/frontend/tests/utils/api.ts`
- `packages/frontend/tests/utils/ui-cleanup.ts`

Status:
- Uses the real **Engine Monitor** UI now.
- No direct backend delete call remains in e2e helpers for engine shutdown.

### Analysis / datasource / UDF / schedule / health-check cleanup
Files:
- `packages/frontend/tests/utils/ui-cleanup.ts`

Status:
- Cleanup flows use visible UI delete controls.

### Analysis creation/import flows
Files:
- `packages/frontend/tests/utils/user-flows.ts`
- `packages/frontend/tests/utils/api.ts`

Status:
- Analysis creation and import use the browser UI.

## Recent migrations

### Direct datasource creation helpers
Files:
- `packages/frontend/tests/utils/api.ts`
- `packages/frontend/tests/utils/user-flows.ts`
- `packages/frontend/src/routes/datasources/new/+page.svelte`

Status:
- Migrated to UI.
- `createDatasource(...)`, `createLargeDatasource(...)`, and `createDatasourceWithDates(...)` now use the real browser upload flow.
- The app now redirects single-create flows to `/datasources?created_id=<created-id>`, so the created datasource id is available through normal browser state without auto-opening preview side effects.

### Shared worker API contexts
Status:
- Removed.
- Datasource creation no longer uses API upload helpers.
- UI setup now reuses hidden authenticated browser setup contexts per worker instead.

## Non-goals
- We are not replacing visible assertions with backend assertions.
- We are not using retries to hide flakes.
- We are not using backend engine shutdown anymore where the UI already supports it.
