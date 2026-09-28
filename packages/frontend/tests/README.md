# Playwright E2E Scope

These tests are the pure user-driven Playwright suite for the frontend.

Rules:

- No API seeding for setup, mutation, or teardown.
- Resource creation and cleanup must go through visible browser flows.
- The required `tests/concurrency.test.ts` probe opens 50 authenticated tabs
  against one shared immutable dataset on every E2E run, first verifies the
  shared-preview single-flight path, and then issues a distinct paginated
  preview request from every tab; set
  `E2E_CONCURRENCY_BROWSERS` only when intentionally running a different load.
  Tabs have independent DOM/runtime state and issue preview requests concurrently
  without duplicating browser bootstrap storage for every simulated user.
- `just test-e2e` and `bun run test:e2e` run this suite.
