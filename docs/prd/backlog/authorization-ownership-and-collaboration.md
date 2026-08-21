# PRD: Authorization, Ownership, and Collaboration

> **Status (audited 2026-08-02): Backlog — depends on the identity model.**
> **Portfolio:** [PRD index](../README.md) · [Feature-overhaul portfolio](data-forge-2.md)

## Purpose

Define who can access, change, and administer resources once real identity exists. This document intentionally follows [Authentication and Identity](authentication-and-identity.md): authorization must not be implemented before the user and session boundaries are settled.

## Decisions required before implementation

- [ ] Decide whether permissions are global, namespace-scoped, or workspace-scoped.
- [ ] Decide whether analyses, datasources, UDFs, and schedules are private or shared by default.
- [ ] Decide the ownership/backfill treatment for existing records.
- [ ] Define the initial role set and which actions require an administrator.

## Audit findings folded into this scope (2026-08)

The 2026-08 codebase audit confirmed concrete gaps this PRD must close:

- Analysis CRUD, engine-run/Iceberg-delete endpoints, namespace/bucket creation, and healthcheck CRUD lack ownership checks.
- `/ws/engines` accepts connections without authentication; chat sessions have no per-user access control.
- Frontend route guarding is client-side only; SvelteKit server hooks should enforce session checks server-side.

## Scope

### Ownership and access control

- [ ] Add owner and updated-by semantics to core resources.
- [ ] Add consistent authenticated and permission dependencies to mutating and protected routes.
- [ ] Define resource visibility, edit-conflict behavior, and ownership-aware search/filtering.

### Teams and administration

- [ ] Add roles, memberships, invitations, revocation, and member-management interfaces.
- [ ] Split personal preferences from global application settings.
- [ ] Gate provider configuration and other sensitive settings behind explicit administrative policy.

### Audit and operational controls

- [ ] Record user-aware audit events for identity, resource, schedule, and settings changes.
- [ ] Define audit visibility and administrative review requirements.
- [ ] Document migration, administrator bootstrap, and deployment/rollout steps.

## Verification

- [ ] Test authorization decisions and ownership/visibility behavior on every core resource type.
- [ ] Test invitation, role-change, revocation, and administrative-setting flows end to end.
- [ ] Validate safe migration/backfill behavior on existing deployments.
