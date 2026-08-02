# PRD: Authentication and Identity

> **Status (audited 2026-08-02): Backlog — product decisions required before implementation.**
> **Portfolio:** [PRD index](../README.md) · [Feature-overhaul portfolio](data-forge-2.md)

## Purpose

Introduce real user identity in place of anonymous client identity. This document owns the user model, authentication methods, sessions, and account-facing experience. It does not define authorization policy or collaboration roles; those belong in [Authorization, Ownership, and Collaboration](authorization-ownership-and-collaboration.md).

## Decisions required before implementation

- [ ] Decide whether the application is authenticated by default or supports a guest/local mode.
- [ ] Decide whether the first release is single-workspace or multi-workspace.
- [ ] Decide session, bearer-token, or hybrid authentication.
- [ ] Decide whether route protection is server-driven, client-driven, or both.
- [ ] Decide email-verification requirements and the account-linking rule for OAuth and password identities.

## Scope

### Identity and session domain

- [ ] Add a canonical user identity with email, display name, avatar, status, timestamps, and preferences.
- [ ] Add provider identity links for password, Google, and GitHub with uniqueness and safe unlink rules.
- [ ] Add durable sessions with expiry, revocation, device metadata, and current-session resolution.

### Authentication services

- [ ] Implement registration, login, logout, current-user, and current-session endpoints.
- [ ] Implement password validation, hashing, reset, and rate limiting.
- [ ] Implement email verification and resend/expiry safeguards.
- [ ] Implement Google and GitHub OAuth callbacks and account-linking semantics.

### Account experience

- [ ] Provide a typed frontend auth/session state with restoration and expiry handling.
- [ ] Add registration, login, verification, reset, and connected-account flows.
- [ ] Add account/profile controls and auth-aware navigation behavior.

## Verification

- [ ] Backend coverage includes identity uniqueness, authentication failures, session expiry/revocation, OAuth callback errors, and linking conflicts.
- [ ] Frontend coverage includes session restoration, protected-route behavior, and account settings.
- [ ] End-to-end coverage includes registration, login/logout, reset, OAuth, and access denial.

## Definition of done

- [ ] Identity, session, and provider-link semantics are documented and tested.
- [ ] A signed-in user can manage their account without exposing secrets or bypassing access controls.
- [ ] The chosen guest/local policy is explicit in both product and deployment documentation.
