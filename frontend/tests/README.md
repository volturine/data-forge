# Playwright Test Scope

These browser tests are intentionally a hybrid suite:

- UI interactions are exercised in the browser.
- Some setup and teardown still use backend API seed helpers in [utils/api.ts](/Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/tests/utils/api.ts:1).

Implications:

- This suite is useful for end-to-end UI verification after state exists.
- It does not prove that every resource-creation flow is fully user-driven.
- When adding a new test, prefer UI setup first. Use API seeding only when the setup would otherwise dominate runtime or make the scenario impractical.

Naming:

- `bun run test:e2e` runs the hybrid Playwright suite.
- `bun run test:hybrid-e2e` is the explicit alias for the same suite.
