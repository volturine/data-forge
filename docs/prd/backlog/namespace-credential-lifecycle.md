# PRD: Namespace Credential Lifecycle

> **Status (2026-10-15): Backlog — not started.**
> **Context:** Follow-up to the implemented [Namespace Credential Management](../implemented/namespace-credential-management.md). The backend already provisions per-namespace reader/builder object-store identities, stores them encrypted, and serves them to workers through the authenticated `GetEngineCredentials` RPC. Namespaces cannot be deleted today, so revocation on deletion is not a current gap.
> **Portfolio:** [PRD index](../README.md)

## Problem

Namespace credentials are created once and never change. An operator cannot rotate a leaked or aging credential, revoke one, or see who used it, without manual object-store administration and a worker restart.

## Scope

- [ ] Record status (active, rotating, revoked, expired) and rotation/expiry/revocation timestamps per namespace role.
- [ ] Rotate: provision the replacement before disabling the old credential. New compute workers use it after the worker cache refreshes; warm compute workers renew through the authenticated channel or restart before the old credential expires.
- [ ] Revoke: mark the record unusable, block new launches, and drain affected compute workers. If namespace deletion is added, revoke both roles after dependent compute workers and storage cleanup finish.
- [ ] Fail readiness with a typed, actionable error for a revoked or expired credential; never fall back to a broader credential.
- [ ] Audit every lifecycle transition without recording secret values.

## Acceptance criteria

1. Rotation works for idle and active shared compute workers without exposing a broader credential.
2. Revoked or expired credentials prevent new work and produce typed readiness failures.
3. Rotation, revocation, and expiry are covered by backend and integration tests, including a warm compute worker with an in-flight job.
4. Audit records exist for every transition and contain no secret values.
