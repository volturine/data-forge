# Hot-path profiling plan

> **Status (audited 2026-08-02): Active — measurements deferred to the next performance cycle.**
> **Portfolio:** [PRD index](../README.md)

_Last audited: 2026-08-02_

The product-path owners and runtime rules are complete in the implemented
[Hot-Path Ownership Map](../implemented/hot-path-ownership-map.md). This active
PRD defines the evidence still needed to attribute the current 54.0% regression.

## Current state

- Current command-level envelope: 411.98–460.99s.
- Current mean: 445.91s.
- Historical mean: 289.55s.
- Regression: +156.36s / +54.0%.
- Stability: five consecutive 351-test passes, zero retries.
- Attribution: unknown; test counts alone are not timing evidence.

## Required measurements

- [ ] Per-file timing or traces for `analysis-editor`, `analysis-pipeline`,
  `analysis-output`, `analysis-operations`, `namespace-isolation`, and `profile`.
- [ ] Worker occupancy during full four-worker E2E load.
- [ ] Request counts for editor open, inline preview, output build, and rebuild.
- [ ] Request counts for namespace switches on Datasources, Monitoring, and Profile.
- [ ] Startup, infrastructure readiness, browser execution, and cleanup time
  separated within the command-level envelope.

## Required output

- [ ] A checked-in measurement record with commands, environment, raw evidence,
  and reproducible calculations.
- [ ] A ranked list of measured bottlenecks mapped to the implemented owners.
- [ ] One focused remediation plan per confirmed bottleneck.
- [ ] Before/after measurements for every implemented optimization.
- [ ] A replacement five-run baseline after optimization.

## Guardrails

- Setup helpers must leave transient pages parked away from heavy routes.
- Namespace-sensitive API reads must not trade correctness for caching speed.
- Preview fanout must not starve visible builds.
- Lost leases must drain without publication.
- Coverage, visible assertions, and zero retries remain non-negotiable.
