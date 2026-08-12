# PRD: Namespace Credential Management

> **Status:** Backlog — follow-up to the implemented [Containerized Polars Engines](../implemented/containerized-polars-engines.md) PRD.
> **Portfolio:** [PRD index](../README.md)

## Summary

Replace the current operator-provided `ENGINE_OBJECT_STORE_CREDENTIALS_JSON` deployment map with backend-managed namespace credentials. The worker must receive only the credentials it is authorized to use, while engine containers continue to receive only short-lived, namespace-scoped runtime material.

## Current Boundary

The containerized engine architecture is implemented. Operators currently provide a complete namespace reader/builder credential map through a protected worker deployment secret. The worker validates it at startup, selects the namespace and role, and bootstraps the engine through a temporary secret `tmpfs`.

This is intentionally operational configuration, not product-managed credential lifecycle. Adding or rotating a namespace credential requires changing deployment configuration and restarting the worker.

## Problem

The current map does not provide product-level provisioning, encrypted persistence, rotation, revocation, auditability, or namespace lifecycle integration. It also makes credential changes depend on deployment access and worker restarts.

## Goals

1. Store namespace reader and builder credentials encrypted at rest using the existing application encryption mechanism.
2. Expose only authenticated internal worker access; never return secrets through public APIs, logs, engine snapshots, or ordinary database reads.
3. Provision, replace, rotate, revoke, and audit credentials without editing deployment JSON or restarting every worker.
4. Revoke credentials as part of namespace deletion after engine teardown and storage cleanup.
5. Keep reader and builder permissions separate and enforce the approved namespace prefixes.
6. Support safe rotation for shared warm engines, including renewal or controlled restart before expiry.
7. Preserve the current engine boundary: containers receive no platform administrator credential and no Docker control surface.
8. Provide a migration path from the operator map without silently broadening access.

## Non-goals

- Changing Docker engine lifecycle, capacity admission, result recovery, or reconciliation.
- Moving Docker control into the backend.
- Returning raw credentials to frontend clients.
- Introducing Kubernetes workload identity in this PRD.
- Per-request credential provisioning before the namespace credential model is proven.

## Target Design

```text
Backend credential service
  -> encrypted namespace credential records
  -> authenticated internal worker access
  -> worker credential cache with bounded lifetime
  -> engine bootstrap tmpfs / authenticated renewal
  -> one namespace + role per engine
```

The backend owns the credential record and lifecycle. The worker remains the only component that selects credentials for an engine. Engine containers receive the minimum reader or builder credential for their identity and namespace.

## Required Contract

Each namespace has distinct reader and builder records with:

- provider and endpoint metadata;
- encrypted access material or a provider reference;
- allowed namespace prefixes;
- status: active, rotating, revoked, or expired;
- creation, rotation, expiry, and revocation timestamps;
- audit metadata without secret values.

Internal worker reads must be authenticated, namespace-scoped, role-scoped, and versioned. A missing, revoked, incomplete, or expired record must fail engine readiness clearly; it must never fall back to a broader credential.

## Rotation and Revocation

- Provision the replacement before disabling the old credential.
- New engines use the replacement immediately after the worker cache refreshes.
- Warm engines renew through the authenticated engine channel or restart before the old credential expires.
- Revocation marks the record unusable, prevents new launches, and drains affected engines.
- Namespace deletion revokes both roles only after dependent engines and storage cleanup complete.
- Every lifecycle transition is auditable without recording secret values.

## Migration

Support one explicit migration mode that imports the operator map into encrypted records. Validate every namespace and role before import, report incomplete entries, and keep the old map disabled after a successful cutover. Do not add a silent fallback between the two sources.

## Acceptance Criteria

1. Credentials are encrypted at rest and cannot be retrieved through public API representations or logs.
2. A worker can read only the namespace and role needed for an engine it supervises.
3. Provisioning, rotation, revocation, expiry, and namespace deletion are covered by backend and integration tests.
4. Rotation works for both idle and active shared engines without exposing a broader credential.
5. Revoked or expired credentials prevent new work and produce typed, actionable readiness failures.
6. Migration from the operator map is explicit, validated, observable, and reversible until cutover.
7. Engine containers retain the existing tmpfs bootstrap boundary and never receive platform administrator credentials.
8. Documentation describes operator configuration as transitional and points to this PRD until the migration ships.

## Evidence Required Before Moving to Active

- Security review of encryption, internal authorization, and audit records.
- Integration test proving reader/builder namespace policy enforcement.
- Rotation test with a warm engine and an in-flight job.
- Revocation and namespace deletion test with no residual access.
- Migration rehearsal from the current deployment map.
- Measured cache and renewal behavior under parallel engine load.
