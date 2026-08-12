# PRD: Containerized Polars Engines

> **Status (completed 2026-08-12): Implemented — Docker-native engine runtime and lifecycle architecture shipped.**
> **Portfolio:** [PRD index](../README.md)

## Summary

Run each Polars engine in its own short-lived container instead of as a Python subprocess inside the worker container. The worker remains the authoritative lifecycle supervisor and command dispatcher; each engine container owns exactly one engine identity and its Polars compute process. Operator-provided namespace credentials are the current deployment contract; credential provisioning and rotation are tracked separately in [Namespace Credential Management](../backlog/namespace-credential-management.md).

The first implementation targets one local Docker daemon in production Docker Compose deployments. It preserves the existing engine identity and durable compute-request contracts while replacing only the engine execution boundary. The executor interface and network protocol must remain suitable for a later Kubernetes executor, but Kubernetes scheduling is not part of this release.

## Problem

Today, each worker-side `ProcessManager` starts a `PolarsComputeEngine` as a Python multiprocessing child. This isolates individual process crashes, but it does not provide container-level resource enforcement, independently versioned engine images, durable runtime identity, or Docker-native inspection and cleanup.

The product needs a hard, visible boundary per engine:

```text
worker container
  -> Docker Engine API
  -> one container per EngineIdentity
  -> one Polars engine server
```

Moving execution into a container also removes the worker and engine shared filesystem assumption. Commands, progress, results, credentials, and export artifacts must therefore cross explicit transport boundaries.

## Goals

1. One live engine identity maps to one dedicated container.
2. Docker enforces CPU and memory limits derived from the engine resource configuration.
3. The worker can create, inspect, stop, kill, remove, and reconcile engine containers.
4. Engine jobs, results, progress, health, and shutdown cross a versioned gRPC boundary rather than multiprocessing queues.
5. Existing identity and reuse rules remain unchanged:
   - shared datasource-preview engine per datasource and namespace;
   - shared interactive engine per analysis and namespace;
   - exclusive engine per build.
6. Lifecycle API calls remain durable and responsive. A queued shutdown completes only after Docker confirms that the container is absent.
7. Engine containers receive no Docker socket, host bind mounts, platform database URL, internal API token, or cross-namespace object-store credentials.
8. Worker restart, build-child failure, idle reaping, and ordinary shutdown leave no orphaned engine containers.
9. Production fails fast when the Docker daemon, runtime network, pinned image digest, or required configured credentials are unavailable.

## Non-goals

- Kubernetes scheduling in the first release.
- Multiple top-level Docker supervisors sharing one deployment or Docker daemon.
- Replacing the worker's build/scheduler process model.
- Keeping the subprocess engine as a production fallback after cutover.
- User-configurable arbitrary container images.
- Building a general S3 proxy or workload-identity platform in the first release.
- Changing datasource-preview, analysis-interactive, or build identity semantics.

## Existing Contracts to Preserve

The implemented engine lifecycle contract remains authoritative:

| Scope | Identity | Reuse | Shutdown owner |
|---|---|---|---|
| Datasource preview | namespace + datasource ID | Shared | Datasource deletion or idle reaper |
| Analysis interactive | namespace + analysis ID | Shared | Analysis deletion, explicit shutdown, or idle reaper |
| Build | namespace + build ID | Exclusive | Build terminal path or worker recovery |

Durable backend compute requests remain the boundary between the API and worker. The Docker executor is internal to the worker and must not move container control into the backend.

## Target Architecture

```text
Backend
  - persists durable compute requests and engine projections
  - never calls Docker
        |
        | existing internal worker protocol
        v
Worker ProcessManager
  - identity, reuse, capacity, idle cleanup, snapshots
        |
        v
DockerEngineExecutor
  - create, inspect, stop, kill, remove, reconcile
        |
        v
ContainerComputeEngine
  - implements the existing ComputeEngine behavior over gRPC
        |
        v
Polars engine container
  - one identity, serial job execution, progress, result, shutdown
        |
        +---- namespace-scoped object-store access
        +---- datasource-specific external database access
```

### Runtime roles

| Role | Responsibility |
|---|---|
| Worker | Authoritative lifecycle supervisor, Docker API owner, command dispatcher, credential selector, and snapshot publisher. |
| Docker executor | Converts a launch specification into a restricted container and reconciles labelled containers. |
| Engine container | Executes one engine identity, exposes the engine gRPC service, and holds only its scoped runtime credentials. |
| Backend | Persists requests, engine snapshots, and lifecycle state. It does not control Docker directly. |
| Object store | Stores namespace data and cross-container staging artifacts. |

### Supported topology

Version 1 supports exactly one top-level worker supervisor for a Data-Forge Docker deployment. That supervisor may continue to create existing build-worker child processes. The parent assigns stable child worker IDs so containers can be labelled and cleaned when a child exits.

Supporting multiple independent Docker supervisors against the same deployment requires distributed container ownership and capacity leases and is deferred with Kubernetes scheduling.

## Engine Runtime Contract

### Protocol

Add an engine-runtime protobuf service in `packages/protocol`. It owns the worker-to-engine network boundary and carries a protocol version on every job submission.

Required operations:

- `Health`: reports readiness, engine identity, image/application version, and protocol version.
- `SubmitJob`: accepts one normalized preview, schema, row-count, or export job and returns its job ID.
- `WatchJob`: streams ordered progress and the terminal job event, with reconnect from a sequence cursor.
- `GetResult`: fetches the terminal result when the watcher reconnects or misses the terminal event.
- `Shutdown`: rejects new work, drains or acknowledges the active job within the cooperative grace period, and exits.

The engine server processes jobs serially, matching the current subprocess behavior. Results are retained by job ID until fetched or until the container terminates. Preview results must be streamed or chunked so they do not rely on gRPC's default unary message limit.

The job request contains the normalized datasource configuration, applied steps, additional datasource configurations, and operation options already prepared by the worker compute service. It does not duplicate the backend-facing durable `ComputeCommandEnvelope`.

### Error contract

Container-native failures must be typed and propagated to the existing durable compute request and engine-run failure paths:

- engine start timeout;
- protocol or image version mismatch;
- gRPC connection loss;
- unexpected container exit;
- Docker-reported OOM kill;
- cooperative shutdown timeout and forced removal;
- invalid job request;
- Polars or datasource execution failure.

An engine crash fails only the affected job. It does not terminate the worker.

## Docker Executor

### Executor boundary

Replace the current resource-ID-only engine factory with an executor launch specification containing:

- full `EngineIdentity`;
- namespace;
- supervisor and owner worker IDs;
- requested and effective resources;
- immutable engine image reference and expected digest;
- Docker network;
- engine RPC port and bootstrap material;
- protocol and application versions;
- scoped object-store credential reference;
- creation timestamp and deployment ID.

The executor returns a container handle used by `ContainerComputeEngine`. `ProcessManager` continues to own identity reuse, per-identity spawn serialization, idle activity, configuration changes, and snapshot publication.

Production has one Docker executor. Unit tests inject a fake executor; there is no production subprocess fallback after cutover.

### Container creation

Each engine container must have:

- the pinned engine image by immutable digest;
- one unique container name and network alias;
- no published host ports;
- a dedicated Data-Forge runtime bridge network;
- no Docker socket, host network, privileged mode, or host bind mounts;
- a non-root runtime user;
- all Linux capabilities dropped;
- `no-new-privileges` enabled;
- a bounded PID limit;
- no automatic restart policy;
- Docker memory derived from `max_memory_mb`;
- Docker CPU quota derived from effective `max_threads`;
- matching Polars thread, memory, and streaming settings as defense in depth;
- labels for deployment, namespace, scope, reuse policy, resource ID, supervisor ID, owner worker ID, protocol version, image digest, and creation time.

The runtime bridge allows the engine to reach the object store and configured external datasource hosts. Platform Postgres and the Docker API are not attached or exposed through that network.

### Startup

1. Resolve and validate the effective resource configuration.
2. Verify that the exact engine digest and runtime network exist.
3. Create the restricted container with labels and the container-only secret `tmpfs`.
4. Start the container; its entrypoint waits for a bounded credential-bootstrap period before serving.
5. Write the credential document into the running container's secret `tmpfs` through the Docker API.
6. Wait for gRPC health with a bounded timeout.
7. Verify engine identity, application version, and protocol version.
8. Publish the active engine snapshot.

Failed startup captures Docker state and logs, removes the container, records a typed failure, and releases the per-identity spawn gate.

### Shutdown

1. Stop accepting new jobs for the identity and publish `stopping`.
2. Request cooperative engine shutdown over gRPC.
3. Wait for container exit for the configured grace period.
4. Ask Docker to stop the container if it remains live.
5. Kill it if the bounded Docker stop also fails.
6. Inspect final exit code and OOM state.
7. Remove the container and its temporary secret material.
8. Confirm absence through Docker.
9. Only then publish the empty/stopped snapshot and complete the durable lifecycle request.

Analysis deletion may continue to enqueue shutdown without delaying its HTTP response. The durable shutdown request itself completes only after step 8.

## Credential Provisioning

### Version 1 decision

Provision two long-lived, namespace-scoped object-store identities per namespace:

| Credential | Engine scopes | Permissions |
|---|---|---|
| Namespace reader | Datasource preview, analysis interactive | List/read the namespace bucket paths required by uploads, clean data, Iceberg metadata, and exports. |
| Namespace builder | Build | Reader permissions plus write/delete within approved build output and runtime-staging prefixes. |

For this release, operators provision these identities and provide the complete namespace-to-role map to the worker through the protected `ENGINE_OBJECT_STORE_CREDENTIALS_JSON` deployment secret. The worker validates the complete map before becoming ready and selects only the matching namespace and role for each engine. Engine containers never receive the platform object-store administrator credential.

Backend-owned provisioning, encrypted persistence, automatic rotation, and revocation are deferred. Adding or rotating a namespace credential currently requires updating the deployment secret and restarting the worker.

Production readiness requires a RustFS compatibility test proving policy enforcement for list, get, ranged get, put, multipart upload, and delete across allowed and denied namespace paths. If the pinned RustFS release cannot reliably create and enforce namespace identities, implementation is blocked until RustFS is upgraded or the fallback below is selected.

### Secret delivery

Do not place object-store credentials in the container's long-lived configured environment, where they become part of inspectable container configuration.

Create a container-only `tmpfs` at `/run/dataforge-secrets`. After the container starts, the worker uses a short-lived Docker exec environment to write a mode-`0400` credential document into that mount; the secret is not part of the container configuration. The engine entrypoint waits for and consumes that document before making its gRPC service ready. The file is removed after loading, credentials remain only in engine memory, and the `tmpfs` disappears with the container.

The credential document includes only:

- object-store endpoint and region;
- access key and secret key;
- optional session token and expiration for future STS support;
- namespace bucket;
- engine identity;
- one-time RPC bearer token.

Anyone with Docker daemon control remains able to inspect engine memory or filesystem state. Docker daemon access is therefore an administrative trust boundary.

### Future temporary credentials

The executor contract and credential document support temporary session credentials from the start. After RustFS passes an STS compatibility suite, replace long-lived namespace credentials with per-container sessions constrained by the same namespace policy and a bounded lifetime.

Shared engines require renewal before expiration. Renewal is sent over the authenticated engine RPC channel and atomically replaces the in-memory credential provider. Failure to renew before the safety deadline stops the engine rather than silently falling back to broader credentials.

### Fallback if namespace credentials are unavailable

The approved fallback is a worker-owned object-store authorization gateway with per-engine tokens. Engines would receive no S3 credentials and would access namespace objects through the gateway. This has a larger implementation and performance cost and must be planned separately before use.

Passing the existing global object-store credentials is allowed only in local development and must be rejected in production.

### Datasource database credentials

Do not provision the Data-Forge platform `DATABASE_URL` into an engine. Credentials for an external database datasource remain part of that datasource's normalized job configuration, are sent only over authenticated engine RPC, and must already be scoped at the source database according to the datasource configuration.

## Cross-container Artifacts

Worker-local temporary paths cannot be sent to an engine container.

For export and download operations:

1. The worker creates a unique staging prefix under `runtime-staging/{engine-id}/{job-id}` in the namespace bucket.
2. The engine writes the artifact to that object-store location.
3. The engine returns artifact metadata rather than a local path.
4. The worker reads or downloads the artifact for notification extraction, size enforcement, download response creation, or Iceberg publication.
5. The worker deletes the staging prefix in `finally` after success, failure, cancellation, or publication fencing loss.
6. Reconciliation removes abandoned staging prefixes belonging to terminal or missing containers.

Presigned URLs may be used for individual staging objects, but they are not the general Iceberg access mechanism because Iceberg discovers metadata, manifests, and data files dynamically.

## Reconciliation and Ownership

### Labels and ownership

All managed containers carry a Data-Forge deployment label and a supervisor-instance label. Build engines additionally carry the assigned build-child worker ID.

The top-level worker assigns child worker IDs before spawning build processes so it can associate a dead child with its engine containers.

### Reconciliation rules

- Before accepting compute requests or build jobs, a newly started top-level supervisor removes containers belonging to the previous supervisor instance for the same deployment.
- When a managed build-child process exits, the parent removes containers carrying that child owner ID.
- The periodic reconciler removes stopped containers after capturing exit metadata.
- A live labelled container with no matching in-memory identity under the current supervisor is treated as orphaned and removed.
- An in-memory identity whose container is missing or stopped is marked failed and removed from the active snapshot.
- Reconciliation is idempotent; missing containers and repeated removals are successful outcomes.
- Containers from another Data-Forge deployment ID are never modified.

## Engine Status and Observability

Replace process-native status with container-native status. Do not retain `process_id` as a compatibility field.

Engine snapshots and persisted engine instances must expose:

- container ID;
- immutable image digest;
- lifecycle status: `starting`, `idle`, `running`, `stopping`, `stopped`, or `failed`;
- requested resource configuration;
- effective Polars resources;
- enforced Docker CPU and memory limits;
- current job, build, and engine-run IDs;
- last activity and last health timestamps;
- termination reason;
- exit code and Docker OOM flag when applicable;
- supervisor and owner worker IDs.

Container stdout/stderr remains available through Docker logs. Worker logs include container ID, engine identity, job correlation ID, and termination metadata without logging commands containing credentials.

## Deployment and Image Ownership

Add a dedicated `engine` target to `docker/Dockerfile` and publish `data-forge-polars-engine` for `linux/amd64` and `linux/arm64` alongside the API, scheduler, and worker images.

Production configuration includes:

- `ENGINE_DOCKER_HOST`;
- `ENGINE_DOCKER_NETWORK`;
- `ENGINE_IMAGE` using `repository@sha256:digest`;
- `ENGINE_START_TIMEOUT_SECONDS`;
- `ENGINE_SHUTDOWN_GRACE_SECONDS`;
- `ENGINE_RPC_PORT`;
- `DATAFORGE_DEPLOYMENT_ID`;
- Docker socket path and group configuration required by the host.

The production Compose worker receives Docker API access; engine containers do not. Linux deployment documentation must explain that Docker daemon access is effectively administrative host access and how the non-root worker user receives socket permission. Rootless and alternate Docker socket paths are configured explicitly rather than auto-discovered.

Runtime does not silently pull an image, accept a mutable substitute, or fall back to a subprocess. Deployment tooling builds or pulls the engine image before worker readiness succeeds.

## Delivery Plan

The work should be implemented as reviewable vertical slices. The old subprocess path may remain while early protocol and image slices are unshipped, but the production cutover removes it in the same change that enables Docker execution.

### Phase 0 — contract and compatibility proof

- Update this PRD and freeze the supported single-supervisor topology.
- Validate the operator-provided namespace reader/builder map at startup.
- Prove Polars, PyArrow, and PyIceberg operations with those credentials.

Exit condition: credential selection and enforcement work end to end without global credentials.

### Phase 1 — engine RPC and standalone server

- Define the engine-runtime protobuf service and typed job/error messages.
- Extract the Polars job runner from multiprocessing queue ownership.
- Implement the one-identity engine gRPC server, serial job execution, result retention, progress streaming, health, and shutdown.
- Add protocol contract tests that run the server without Docker.
- Add the non-root engine Docker target and image health check.

Exit condition: the standalone engine server passes the existing preview, schema, row-count, export, progress, and failure behavior tests.

### Phase 2 — credential and artifact boundaries

- Load the operator-provided namespace credential map only in the worker.
- Reject missing, incomplete, or platform-wide credentials in production.
- Implement the container `tmpfs` secret bootstrap document.
- Replace worker-local export paths with namespace staging objects.
- Add staging cleanup and artifact parity tests.

Exit condition: an engine server can execute every operation without a shared filesystem or global object-store credential.

### Phase 3 — Docker executor

- Add the executor launch specification, container handle, and fake test executor.
- Implement Docker create, inspect, health wait, logs, stop, kill, remove, and image/network validation.
- Implement `ContainerComputeEngine` over gRPC.
- Map Docker exit and OOM state to typed engine failures.
- Add unit tests with a fake Docker client and integration tests against a real Docker daemon.

Exit condition: the executor creates a correctly restricted container and executes all engine job types through it.

### Phase 4 — lifecycle, reconciliation, and status

- Refactor `ProcessManager` to use the executor while preserving identity and reuse rules.
- Assign build-child worker IDs in the parent before process spawn.
- Add startup, dead-child, periodic, and shutdown reconciliation.
- Replace process status with container-native protocol and persistence fields.
- Update backend projections and frontend engine monitoring.
- Verify delete, configure, idle reap, build terminal, crash, OOM, and worker restart paths.

Exit condition: every lifecycle path removes its container and publishes the correct durable state.

### Phase 5 — production cutover and release

- Add the Docker runtime network and worker Docker socket configuration to Compose.
- Add engine image build, multi-architecture publish, digest reporting, and release documentation.
- Add production readiness checks for daemon, permission, network, image digest, and configured credentials.
- Switch the production engine factory to Docker.
- Delete `PolarsComputeEngine` multiprocessing management and queue-only command/result code.
- Remove obsolete subprocess tests and replace them with executor contract tests.
- Run the full verification and repeated container lifecycle E2E suite.

Exit condition: production has one supported Docker-native engine path and no subprocess fallback.

## Code Map

Expected primary areas:

- `packages/protocol/proto/dataforge_protocol/` — engine RPC, status, errors, generated contracts
- `packages/worker/runtime/compute_manager.py` — preserved identity and lifecycle ownership
- `packages/worker/runtime/compute_engine.py` — job runner extraction and subprocess removal
- `packages/worker/runtime/compute_service.py` — artifact staging boundary
- `packages/worker/runtime/` — executor, container client, engine server, reconciliation, credential bootstrap
- `packages/backend/backend_core/engine_instances_service.py` — container-native snapshots
- `packages/backend/backend_core/persistence/` — engine status and lifecycle persistence
- `packages/frontend/src/lib/` — generated status types and engine monitoring
- `docker/Dockerfile` — engine image target
- `docker/docker-compose.yml` — Docker access and runtime network
- `.github/workflows/` — engine image build and publication
- `docs/ENV_VARIABLES.md` and `docs/DEPLOYMENT.md` — runtime and security configuration

Exact new filenames should follow the existing package boundaries and keep Docker control, RPC transport, job execution, and credential provisioning as separate concerns.

## Verification Matrix

### Unit and contract tests

- Engine RPC validation, version mismatch, progress ordering, reconnect, and terminal-result recovery.
- Resource normalization and exact Docker CPU/memory translation.
- Container labels, security configuration, network, and immutable image validation.
- Per-identity concurrent spawn serialization.
- Shared reuse, exclusive build identity, config-change restart, and idle eviction.
- Credential selection, encryption, masking, rotation, and revocation.
- Allowed and denied namespace object-store operations.
- Artifact staging cleanup on success, failure, cancellation, and publication fencing loss.
- Exit code, OOM, health timeout, RPC loss, and forced-shutdown error mapping.

### Docker integration tests

- One labelled container is created for a resolved identity.
- Shared identities reuse the same healthy container.
- Exclusive build identities never share a container.
- Container inspection reports the exact resource limits and restrictions.
- Engine has no Docker socket, host bind mount, global object credential, platform database URL, or internal API token.
- Preview, schema, row count, download, export, and build execute across gRPC.
- Killing the engine fails only the affected request and leaves the worker healthy.
- OOM termination is reported distinctly.
- Cooperative shutdown removes the container.
- Hung shutdown escalates and still removes the container.
- Supervisor restart removes prior labelled containers.
- Dead build-child cleanup removes its exclusive build container.
- Containers from another deployment label are untouched.

### Product E2E tests

- Datasource preview creates and reuses its container.
- Analysis navigation does not tear down the shared engine.
- Analysis deletion responds without waiting and eventually removes its engine.
- Datasource deletion finalizes only after preview-engine removal.
- Each build creates one exclusive container and removes it at terminal state.
- Engine monitoring shows container identity, resources, lifecycle, and termination reason.

### Release gate

```bash
just verify
just test
just test-e2e
```

The Docker integration and lifecycle E2E suite must also pass repeatedly without orphaned containers, staging objects, runtime warnings, or leaked credentials.

## Acceptance Criteria

1. Creating an analysis preview or build creates exactly one labelled engine container for its resolved identity.
2. Shared identities reuse the same healthy container; exclusive build identities do not.
3. Docker inspection confirms the requested CPU and memory constraints and required security restrictions.
4. Engine containers can access only their namespace object-store paths and receive no global platform credentials or Docker control surface.
5. An engine crash or OOM is contained to that engine and reported as a typed failed compute request without killing the worker.
6. Analysis deletion returns promptly; its queued shutdown completes only after the engine container is absent and the active snapshot is empty.
7. Datasource deletion, idle cleanup, build completion, dead-child cleanup, and worker restart reconciliation leave no orphaned containers or staging artifacts.
8. Preview, schema, row count, download, export, and build results remain behaviorally compatible with the current engine implementation.
9. E2E tests cover creation, reuse, resource limits, credential isolation, deletion teardown, crash/OOM handling, and orphan reconciliation against Docker.
10. Production fails fast when the Docker daemon, permission, runtime network, exact engine digest, or configured scoped credentials are unavailable.
11. The production worker contains no subprocess engine fallback after cutover.

## Deferred Decisions

- Kubernetes pod executor and scheduling contract details.
- Distributed capacity and ownership leases for multiple Docker supervisors.
- Replacing namespace credentials with per-engine STS sessions after RustFS conformance is proven.
- OIDC workload identity or a worker-owned object-store authorization gateway.
