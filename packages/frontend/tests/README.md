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
- `just test-e2e` runs this suite in its own private containerized test
  enclave, daemon, network, and volumes. Run it with Docker and `just`
  installed on the host; Playwright and browser dependencies are supplied
  inside the enclave, and all browser containers count against its resource
  budget. E2E defaults to 90% of Docker's available memory; its controller
  receives 512 MiB and at least 0.5 CPUs or 20% of its CPU budget, whichever
  is greater, with the remainder assigned to the private daemon. It exports
  logs and diagnostics to `.test-artifacts/<run-id>` on success and failure.
  Resource caps apply to
  this invocation; concurrent invocations each have their own caps and still
  share the host's finite CPU and memory.
