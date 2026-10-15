# PRD: 2,000-User Capacity Validation

> **Status (2026-10-15): Backlog — not started.**
> **Context:** Follow-up to the implemented [Capacity-First Runtime Optimization](../implemented/capacity-first-runtime-optimization.md), which shipped the overhead reductions, runtime contracts, scale policy, and readiness gates. That work proved the 2,000-session connected-WebSocket profile only. This PRD covers the rest of the 2,000-user claim.
> **Portfolio:** [PRD index](../README.md)

## Objective

Prove that the minimal topology (one API replica × one Uvicorn process, one runtime coordinator, one worker manager, separate compute-worker containers) serves a representative 2,000-user workload with no lost accepted work and no unexplained errors. Scale a layer only when these measurements show it is saturated, following the [scale policy](../implemented/capacity-first-runtime-optimization.md#scale-only-after-identifying-the-saturated-layer).

## Profiles

Do not infer compute demand from account or tab count. Benchmark these profiles
separately on the minimal topology:

1. **Connected-session profile:** 2,000 authenticated browser sessions with
   realistic idle/heartbeat/WebSocket behavior. Measure memory, open sockets,
   loop lag, reconnects, and API readiness.
2. **Interactive API profile:** 2,000 sessions with a representative mix of
   bootstrap/auth/config reads, navigation, saves, and status subscriptions.
   Derive request rates from available product/E2E traces; publish the assumed
   active-user ratio and request mix with each result.
3. **Compute profile:** vary active unique RIDs and commands independently.
   Include many tabs sharing one RID and identical command, one hot RID with
   distinct commands, and many unique RIDs. Measure queue wait and worker cold
   starts; do not call these dimensions “users.”
4. **Resilience profile:** kill an API process during a request, interrupt
   notifications, restart the coordinator, and kill a compute worker during
   publication. Accepted work must finish or reach an explicit terminal error;
   unrelated RIDs must continue.

Keep the standard 3×5 E2E suite and permanent 50-tab probe in CI. They are
correctness/readiness gates, not substitutes for sustained 2,000-session load
tests. Define p95/p99 latency and error thresholds before claiming the target;
report throughput, queue age, API loop lag, DB checkout/lock waits, coordinator
RPC lane wait, worker starts, executor occupancy, and CPU/memory in the same run.

## Already proven

- Connected-session profile: 2,000 authenticated WebSocket sessions pass (`just test-e2e-capacity`).
- Resilience: the coordinator-takeover-during-publication case passes.

## Remaining scope

- [ ] Publish the assumed active-user ratio and request mix, then run the interactive API profile.
- [ ] Run the compute profile across shared-RID, hot-RID, and many-unique-RID mixes.
- [ ] Run the remaining resilience cases: API process kill mid-request, interrupted notifications, and compute-worker kill during publication with unrelated RIDs continuing.
- [ ] Define p95/p99 latency and error SLOs before measuring, and record them with each result.

## Definition of done

- The 1×1 API topology has repeatable 2,000-user results for every profile, with the workload assumptions, SLOs, and resource profile recorded.
- No avoidable API/coordinator/worker/DB round trips, scans, polls, oversized executor fan-out, or repeated container starts dominate measured requests.
- Any added process or replica is justified by a measured bottleneck and improves the relevant p95/throughput without increasing errors or destabilizing other services.
