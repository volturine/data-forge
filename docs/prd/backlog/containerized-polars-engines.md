# PRD: Containerized Polars Engines

> **Status (2026-08-09): Backlog — approved architecture direction, not implemented.**
> **Portfolio:** [PRD index](../README.md)

## Summary

Run each Polars engine in its own short-lived container instead of as a Python subprocess inside the worker container. The worker becomes the lifecycle supervisor; the engine container owns only one engine identity and its compute process.

The first implementation targets the local Docker daemon in production deployments. The lifecycle and transport contracts must not prevent a later Kubernetes executor.

## Problem

Today, the worker container starts each `PolarsComputeEngine` as a Python multiprocessing child. The process boundary protects the worker from individual engine crashes, but it does not provide container-level resource isolation, image ownership, or independent observability.

The product needs a hard, visible boundary per engine:

```
worker container → container runtime → one engine container → Polars process
```

## Goals

1. One live engine identity maps to one dedicated container.
2. Docker enforces the engine CPU and memory limits derived from its resource configuration.
3. The worker can create, inspect, stop, and forcibly remove an engine container without blocking API lifecycle responses.
4. Engine commands, results, progress, and status cross a versioned network boundary rather than multiprocessing queues.
5. Existing identity and reuse rules remain unchanged:
   - shared datasource-preview engine per datasource and namespace;
   - shared interactive engine per analysis and namespace;
   - exclusive engine per build.
6. Shutdown is observable: after completion, the container is absent and the engine snapshot no longer reports it.
7. Engine containers cannot access host paths or Docker control surfaces beyond the explicitly required network and object-store credentials.

## Non-goals

- Kubernetes scheduling in the first release.
- Replacing the worker’s build/scheduler process model.
- Keeping the subprocess engine as a production fallback.
- User-configurable arbitrary container images.

## Architecture

### Runtime roles

| Role | Responsibility |
|---|---|
| Worker | Authoritative lifecycle supervisor and command dispatcher. Owns Docker API access. |
| Engine container | Executes one Polars engine identity and exposes the engine RPC service. |
| Backend | Continues to persist requests, engine snapshots, and lifecycle state. It does not control Docker directly. |
| Object store/Postgres | Reached through the configured runtime network and scoped credentials. |

### Lifecycle

1. The worker resolves an engine identity and reuses its container only when the identity is shared.
2. On first use, the worker creates a container from the pinned engine image with namespace labels, identity labels, network attachment, resource limits, and a per-engine RPC endpoint.
3. The worker waits for the engine health check, publishes an active snapshot, and forwards compute commands over RPC.
4. On analysis/datasource deletion, build completion, idle reaping, or explicit shutdown, the worker requests cooperative engine shutdown.
5. If the container does not stop within its bounded grace period, the worker kills and removes it.
6. Only after Docker confirms removal does the worker publish the empty/stopped snapshot and complete the lifecycle request.

### Isolation and configuration

- Set Docker CPU and memory limits from `max_threads` and `max_memory_mb`; Polars receives matching limits as defense in depth.
- Use a dedicated runtime network; do not mount the Docker socket into engine containers.
- Pass only the engine’s runtime configuration and scoped object-store/database credentials.
- Label containers with namespace, scope, resource ID, worker ID, protocol version, and creation time for reconciliation.
- Pin the engine image by immutable digest in production.

### Transport

Replace the current in-process multiprocessing queues with a small versioned gRPC service owned by the engine image. It must support health, execute command, stream progress, fetch result, and shutdown. Existing protobuf command and response payloads should be reused where possible; the engine-specific RPC wrapper owns network and lifecycle semantics.

## Delivery plan

### Phase 1 — contract and image

- Define the engine RPC service and health contract in `packages/protocol`.
- Create a minimal, pinned Polars engine image with a non-root runtime user.
- Add Docker runtime configuration and image/version documentation.

### Phase 2 — Docker executor

- Introduce an executor interface in the worker and implement the Docker executor.
- Move spawn/status/shutdown behavior from `PolarsComputeEngine` subprocess management to the executor.
- Add label-based reconciliation for containers left behind after worker restart.

### Phase 3 — lifecycle and observability

- Make engine snapshots reflect container ID, image digest, resource limits, and termination reason.
- Verify delete, idle reap, build completion, crash, and worker restart cleanup paths.
- Remove the production subprocess executor after the Docker path is complete.

## Acceptance criteria

1. Creating an analysis preview or build creates exactly one labelled engine container for its resolved identity.
2. Shared identities reuse the same healthy container; exclusive build identities do not.
3. An engine crash is contained to that engine and is reported as a failed compute request without killing the worker.
4. Deleting an analysis returns promptly, then completes its shutdown request only after the engine container has been removed and the engine snapshot is empty.
5. Idle cleanup and worker restart reconciliation leave no orphaned engine containers.
6. E2E tests cover container creation, reuse, resource limits, deletion teardown, and orphan reconciliation against Docker.
7. Production deployment fails fast when the configured container runtime or pinned engine image is unavailable.

## Open decisions

- Exact database/object-store credential scoping for engine containers.
- Whether engine RPC uses worker-assigned ports or an internal request stream.
- Kubernetes executor requirements and scheduling interface, deferred until Docker implementation proves the contract.
