# PRD: Build Observability

> **Status (audited 2026-08-02): Backlog — expansion beyond the shipped live build-preview core.**
> **Portfolio:** [PRD index](../README.md)

## Purpose

Extend the shipped [Build Preview](../implemented/build-preview.md) experience with
operational detail that is useful for diagnosis, without widening the core preview
contract or re-opening its completed rollout.

## Scope

- [ ] Add bounded, readable log streaming with redaction and rate limits.
- [ ] Add per-worker and per-build resource charts where the measurements are reliable.
- [ ] Add filtering and drill-down for large build histories and monitoring views.
- [ ] Define retention, sampling, and access-control rules for diagnostic data.

## Non-goals

- Replacing the existing live build state/replay protocol.
- Treating raw process logs as a permanent, unbounded data store.

## Verification

- [ ] Test reconnect/replay behavior, redaction, and rate limits.
- [ ] Test chart correctness against known build and worker data.
- [ ] Verify the added diagnostics do not regress build throughput or preview latency.
