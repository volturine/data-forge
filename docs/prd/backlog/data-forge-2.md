# PRD Portfolio: Feature Overhaul

> **Status (audited 2026-08-02): Backlog — portfolio and sequencing document.**
> **Portfolio:** [PRD index](../README.md)

## Purpose

This is deliberately not an implementation PRD. It is the small, cross-feature
portfolio for the future overhaul: it records order, dependencies, and the shared
definition of readiness. Each feature owns its requirements and acceptance criteria
in its focused PRD.

## Feature PRDs

| Feature | Status | Dependency |
|---|---|---|
| [Authentication and Identity](authentication-and-identity.md) | Backlog | Product identity decisions |
| [Authorization, Ownership, and Collaboration](authorization-ownership-and-collaboration.md) | Backlog | Authentication and identity |
| [Application Shell and Shared Panels](application-shell.md) | Backlog | Navigation decisions; can otherwise proceed independently |
| [Lineage Revamp](../active/lineage-revamp.md) | Active — partially implemented | Can proceed independently of identity |

## Recommended sequence

1. Resolve the identity, workspace, permissions, and guest/local-product decisions.
2. Implement and verify authentication and account management.
3. Establish ownership and authorization before adding collaboration/admin features.
4. Run the application-shell redesign in parallel with lineage work where the chosen navigation model permits it.
5. Complete migration, rollout, and documentation only after each feature's own acceptance criteria pass.

## Cross-feature requirements

- [ ] A feature does not start until its documented product decisions are resolved.
- [ ] Every mutation has explicit authorization and ownership semantics before collaboration is enabled.
- [ ] Each feature includes backend, frontend, end-to-end, and migration/rollout verification proportional to its risk.
- [ ] No legacy anonymous or ownership behavior is retained without an explicit, documented product decision.

## Definition of ready

- [ ] Scope boundaries and dependencies are clear.
- [ ] Required migrations and rollout risks are identified.
- [ ] Feature-level acceptance criteria and test strategy are written.
- [ ] Security and privacy implications have been reviewed.
