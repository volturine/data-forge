# Playwright E2E Scope

These tests are the pure user-driven Playwright suite for the frontend.

Rules:

- No API seeding for setup, mutation, or teardown.
- Resource creation and cleanup must go through visible browser flows.
- `just test-e2e` and `bun run test:e2e` run this suite.
