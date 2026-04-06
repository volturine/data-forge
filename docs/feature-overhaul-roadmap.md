# Feature Overhaul Roadmap

## Document Control

- **Product:** Data-Forge Analysis Platform
- **Status:** Draft
- **Last Updated:** 2026-03-30
- **Owner:** Product + Engineering
- **Purpose:** Execution roadmap for the user/auth, app-shell, and lineage overhaul

---

## 1. Intent

This document defines the implementation roadmap for a major feature overhaul of the application. It focuses on three connected areas:

1. Full user support and authentication
2. Global navigation and left-panel redesign
3. Lineage correctness and UX redesign

This is a **tasks-only** roadmap. It is meant to be followed structurally, phase by phase, without prematurely locking implementation details.

---

## 2. Overhaul Goals

### 2.1 Primary Goals

- Add full user registration and account support
- Add login via email/password, Google, and GitHub
- Introduce proper session handling and access control
- Redesign the app shell so navigation and panels are coherent across the product
- Fix lineage semantics so internal tab/code flow is not misrepresented as derived datasets
- Expand lineage into a clearer, more useful dependency exploration tool

### 2.2 Desired Outcomes

- The app can support real user identity instead of anonymous local-only usage
- Sensitive settings and future collaboration features can be safely gated
- Navigation feels intentional, consistent, and scalable
- Lineage becomes trustworthy for both upstream and downstream understanding
- The system is ready for multi-user and collaboration features later

### 2.3 Explicit Non-Goals for This Document

- This document does not define detailed API payloads
- This document does not define final database schemas
- This document does not contain implementation code
- This document does not commit to rollout dates

---

## 3. Guiding Product Decisions To Make Early

These decisions must be resolved before implementation starts or very early in Phase 1.

### 3.1 Identity Model

- [ ] Decide whether the app is strictly authenticated by default or supports a guest/local mode
- [ ] Decide whether the product remains single-workspace initially or introduces multi-workspace semantics immediately
- [ ] Decide whether permissions are global, namespace-scoped, or workspace-scoped
- [ ] Decide whether all existing resources become owned resources or whether some remain globally visible

### 3.2 Auth Architecture

- [ ] Decide whether auth uses secure server sessions, bearer tokens, or a hybrid pattern
- [ ] Decide whether frontend route protection is server-driven, client-driven, or both
- [ ] Decide how OAuth-linked accounts and password-based accounts merge into a single user identity
- [ ] Decide whether email verification is mandatory before first app access or only before sensitive actions

### 3.3 Lineage Semantics

- [ ] Decide the canonical distinction between dataset lineage and code lineage
- [ ] Decide whether tabs are visible as first-class nodes or only as expand-on-demand analysis internals
- [ ] Decide whether intermediate tab outputs are persisted artifacts, ephemeral artifacts, or analysis internals in lineage terms
- [ ] Decide what the default lineage view should optimize for: clarity, completeness, or debug depth

### 3.4 App Shell Model

- [ ] Decide whether the primary navigation becomes a full left sidebar, a collapsible icon rail, or a hybrid shell
- [ ] Decide whether route-level side panels should share one reusable framework
- [ ] Decide which routes receive a shared panel treatment in the first pass

---

## 4. Implementation Phases

The recommended execution order is:

1. Foundation and architecture decisions
2. User domain and auth backend
3. Frontend auth flows and account UX
4. App-shell and left-panel redesign
5. Lineage correctness overhaul
6. Lineage UX expansion
7. Permissions, collaboration groundwork, and admin hardening
8. Documentation, migration, and rollout

---

## 5. Phase 0 — Foundation and Discovery Tasks

### 5.1 Product and System Framing

- [ ] Confirm the app is moving from anonymous client identity to real user identity
- [ ] Define target user modes: solo local user, team user, admin user
- [ ] Define whether resources are private-by-default or shared-by-default
- [ ] Define whether namespaces are security boundaries or only organizational groupings
- [ ] Define how existing deployments transition to the new auth model

### 5.2 Architecture Inventory Tasks

- [ ] Inventory backend routes that will require authentication or authorization
- [ ] Inventory frontend pages that need guest/auth/protected treatment
- [ ] Inventory data models that require ownership fields
- [ ] Inventory settings flows that must become admin-only
- [ ] Inventory all current lineage generation points and dependency assumptions
- [ ] Inventory all current left-panel or fixed-aside implementations
- [ ] Inventory current audit logging fields that should become user-aware

### 5.3 Delivery Planning Tasks

- [ ] Break all work into backend, frontend, and verification streams
- [ ] Identify tasks that can safely run in parallel after auth architecture is fixed
- [ ] Identify tasks that require migrations before UI changes
- [ ] Define acceptance criteria for each major epic
- [ ] Define regression areas requiring dedicated tests

---

## 6. Phase 1 — User Domain and Identity Foundation

### 6.1 Core User Model

- [ ] Add a canonical user domain model
- [ ] Add unique email identity handling
- [ ] Add display name support
- [ ] Add avatar URL support
- [ ] Add account status support: active, disabled, pending, deleted
- [ ] Add created-at, updated-at, and last-login-at tracking
- [ ] Add email verification status
- [ ] Add password-present indicator
- [ ] Add profile preferences container

### 6.2 Auth Identity Links

- [ ] Add provider identity linkage model
- [ ] Add provider type support for password, Google, and GitHub
- [ ] Add provider subject uniqueness rules
- [ ] Add provider metadata storage for display name/avatar provenance if desired
- [ ] Add provider-linked timestamp tracking
- [ ] Add unlink safety rules so the last usable login method cannot be removed accidentally

### 6.3 Session Model

- [ ] Add session persistence model
- [ ] Add session expiration model
- [ ] Add device/session metadata fields
- [ ] Add session revocation capability
- [ ] Add logout-all-sessions capability groundwork
- [ ] Add server-side current-session resolution

### 6.4 Ownership Model

- [ ] Add ownership strategy for analyses
- [ ] Add ownership strategy for datasources
- [ ] Add ownership strategy for UDFs
- [ ] Add updated-by tracking where useful
- [ ] Define whether schedules are user-owned, namespace-owned, or workspace-owned
- [ ] Define legacy-record backfill strategy for ownership fields

### 6.5 User Preferences Model

- [ ] Add theme preference support under the user profile
- [ ] Add default namespace/workspace preference support
- [ ] Add notification preferences support
- [ ] Add onboarding completion state support
- [ ] Add UI preference support for panel behavior if desired

---

## 7. Phase 2 — Authentication Backend Tasks

### 7.1 Registration and Login Foundations

- [ ] Add registration endpoint(s)
- [ ] Add login endpoint(s)
- [ ] Add logout endpoint(s)
- [ ] Add current-user endpoint
- [ ] Add current-session endpoint
- [ ] Add consistent auth error schema
- [ ] Add auth dependency for protected routes
- [ ] Add permission dependency for admin or future role-gated routes

### 7.2 Password Authentication

- [ ] Add password hashing workflow
- [ ] Add password validation rules
- [ ] Add duplicate-email protection
- [ ] Add disabled-account login rejection
- [ ] Add invalid-credential handling with safe messaging
- [ ] Add rate limiting or throttling for login attempts
- [ ] Add password change flow for authenticated users

### 7.3 Email Verification

- [ ] Add email verification token issuance
- [ ] Add email verification token validation
- [ ] Add email verification completion endpoint
- [ ] Add resend verification capability
- [ ] Add expiry handling for verification tokens
- [ ] Add anti-abuse protections for verification resends

### 7.4 Password Reset

- [ ] Add forgot-password request flow
- [ ] Add password reset token issuance
- [ ] Add password reset completion flow
- [ ] Add token expiry and single-use guarantees
- [ ] Add anti-enumeration response behavior
- [ ] Add anti-abuse protections for reset requests

### 7.5 Google OAuth Backend

- [ ] Add Google provider configuration support
- [ ] Add Google login initiation route
- [ ] Add Google callback route
- [ ] Add Google account-linking logic
- [ ] Add Google-first account creation logic
- [ ] Add Google-to-existing-user merge rules
- [ ] Add denied-consent and invalid-callback handling

### 7.6 GitHub OAuth Backend

- [ ] Add GitHub provider configuration support
- [ ] Add GitHub login initiation route
- [ ] Add GitHub callback route
- [ ] Add GitHub account-linking logic
- [ ] Add GitHub-first account creation logic
- [ ] Add GitHub-to-existing-user merge rules
- [ ] Add missing/private-email fallback handling
- [ ] Add denied-consent and invalid-callback handling

### 7.7 Unified Account Linking Rules

- [ ] Prevent one OAuth identity from linking to multiple app users
- [ ] Define behavior when OAuth email matches an existing password account
- [ ] Define behavior when OAuth email is absent or ambiguous
- [ ] Add explicit link-provider endpoint(s)
- [ ] Add explicit unlink-provider endpoint(s)
- [ ] Add add-password-to-OAuth-account flow
- [ ] Add safe failure handling for provider conflicts

### 7.8 Auth Security Hardening

- [ ] Add session invalidation on logout
- [ ] Add session invalidation on password reset if required
- [ ] Add suspicious-auth-event logging
- [ ] Add audit logging for registration, login, logout, reset, verification, provider link, provider unlink
- [ ] Add secure redirect URI validation
- [ ] Add environment validation for auth secrets and provider credentials
- [ ] Add auth-compatible CORS review

---

## 8. Phase 3 — Frontend Auth and Account UX Tasks

### 8.1 Global Auth State

- [ ] Add frontend auth/session store
- [ ] Add app boot current-user resolution
- [ ] Add protected-route behavior
- [ ] Add guest-only route behavior for login/register pages
- [ ] Add loading/unknown-auth state handling
- [ ] Add auth-aware API client behavior
- [ ] Add invalid-session recovery behavior

### 8.2 Auth Screens

- [ ] Add registration page
- [ ] Add login page
- [ ] Add forgot-password page
- [ ] Add reset-password page
- [ ] Add email verification page
- [ ] Add invite acceptance page if invitations are included early
- [ ] Add provider callback processing screen
- [ ] Add access-denied state or page
- [ ] Add session-expired UX

### 8.3 Registration UX Tasks

- [ ] Add strong but simple registration form UX
- [ ] Add password strength messaging
- [ ] Add duplicate-account messaging
- [ ] Add verification-pending state messaging
- [ ] Add Google registration entry point
- [ ] Add GitHub registration entry point
- [ ] Add post-registration onboarding redirect

### 8.4 Login UX Tasks

- [ ] Add email/password login form UX
- [ ] Add Google sign-in button UX
- [ ] Add GitHub sign-in button UX
- [ ] Add error-state handling for invalid credentials and callback failures
- [ ] Add remember-me or session-persistence UX if applicable
- [ ] Add switch path between login and registration

### 8.5 Account and Profile UX

- [ ] Add account menu in the app shell
- [ ] Add profile page or profile settings section
- [ ] Add display name editing
- [ ] Add avatar editing or provider-synced avatar behavior
- [ ] Add connected accounts management UI
- [ ] Add change password UI
- [ ] Add sessions/devices management UI
- [ ] Add notification preferences UI
- [ ] Add account deletion/deactivation UI if supported

### 8.6 Auth-Aware Shell Behavior

- [ ] Show login/register entry points for unauthenticated users
- [ ] Show user/account menu for authenticated users
- [ ] Gate settings based on role or auth state
- [ ] Gate sensitive pages or actions based on auth state
- [ ] Add workspace/namespace switcher behavior that fits the new identity model

---

## 9. Phase 4 — Roles, Permissions, and Team Foundations

### 9.1 Role Model Tasks

- [ ] Define base roles: owner, admin, editor, viewer
- [ ] Define scope of each role
- [ ] Define whether roles are workspace-wide, namespace-wide, or mixed
- [ ] Define privileged operations requiring admin access
- [ ] Define read-only mode behavior

### 9.2 Access Control Tasks

- [ ] Gate settings routes and UI for admins only
- [ ] Gate membership management for admins only
- [ ] Gate resource mutation by owner/editor permissions
- [ ] Gate resource visibility according to ownership and sharing rules
- [ ] Add access-denied responses and UI handling

### 9.3 Invitation and Membership Tasks

- [ ] Add invitation model
- [ ] Add invite-by-email flow
- [ ] Add invitation acceptance flow
- [ ] Add invitation expiry handling
- [ ] Add invitation resend and revoke flows
- [ ] Add membership listing and role-change flows

---

## 10. Phase 5 — Global App Shell and Left-Panel Overhaul

### 10.1 Navigation Model Tasks

- [ ] Replace the current text-only top navigation with a scalable app shell
- [ ] Choose final shell model: sidebar, icon rail, or hybrid
- [ ] Add icons to primary navigation destinations
- [ ] Add robust active-link handling for nested and related routes
- [ ] Add consistent route grouping and destination naming
- [ ] Add shell support for authenticated and unauthenticated states
- [ ] Add shell support for workspace/namespace switching
- [ ] Add shell support for account entry points

### 10.2 Shared Panel Framework Tasks

- [ ] Design a reusable left-panel/page-panel framework
- [ ] Standardize panel width tokens
- [ ] Standardize collapse and expand behavior
- [ ] Standardize persisted panel state behavior
- [ ] Standardize mobile behavior for panels
- [ ] Standardize loading, empty, and error states inside panels
- [ ] Standardize sticky headers and panel scroll behavior
- [ ] Standardize resize behavior if resizing is supported

### 10.3 Analyses Route Adoption Tasks

- [ ] Move analyses list into the new shell conventions
- [ ] Review analysis editor left panel against the shared panel framework
- [ ] Review analysis editor right/bottom configuration panel alignment with the shared panel model
- [ ] Remove layout hacks that mirror panel widths in multiple places
- [ ] Normalize panel collapse behavior in the analysis editor

### 10.4 Datasources Route Adoption Tasks

- [ ] Move datasources page into the shared shell and panel framework
- [ ] Replace fixed non-responsive aside behavior
- [ ] Decide whether datasource config remains inline, moves to detail panel, or becomes hybrid
- [ ] Add mobile-appropriate datasource browsing behavior

### 10.5 Lineage Route Adoption Tasks

- [ ] Move lineage page into the shared shell and panel framework
- [ ] Replace hardcoded lineage aside layout with reusable panel behavior
- [ ] Align lineage detail panel behavior with other route-level panels
- [ ] Add mobile fallback behavior for lineage exploration

### 10.6 Nice-To-Have Navigation Tasks

- [ ] Add recent items list
- [ ] Add favorites or pinned items
- [ ] Add quick-create actions in shell
- [ ] Add command palette
- [ ] Add keyboard shortcuts for navigation
- [ ] Add notification or status badges where useful

---

## 11. Phase 6 — Lineage Semantics and Correctness Overhaul

### 11.1 Canonical Lineage Model Tasks

- [ ] Define canonical node types for lineage
- [ ] Define canonical edge types for lineage
- [ ] Separate dataset lineage from analysis/code lineage
- [ ] Define whether intermediate tab outputs are first-class lineage entities or analysis-internal artifacts
- [ ] Define whether persisted outputs and ephemeral intermediates use different visual/semantic treatment
- [ ] Define branch-aware lineage expectations clearly

### 11.2 Correctness Tasks

- [ ] Stop representing internal tab chaining as derived datasets in the default view
- [ ] Ensure derived dataset edges represent actual dataset provenance, not just internal analysis flow
- [ ] Represent code dependency separately from datasource dependency
- [ ] Fix multi-input dependency capture for join/union and similar operations
- [ ] Fix recursive upstream lineage traversal depth
- [ ] Add downstream traversal support
- [ ] Fix namespace-aware lineage responses and messaging
- [ ] Fix branch selection and branch-specific lineage accuracy
- [ ] Ensure lineage reflects real run-time dependencies where available
- [ ] Ensure missing dependency registration gaps are closed

### 11.3 Data Recording Tasks

- [ ] Decide where and when lineage dependencies are recorded
- [ ] Record dataset dependencies at build/run time more explicitly
- [ ] Record code or tab-level dependencies separately from dataset dependencies
- [ ] Record intermediate outputs in a way that does not pollute dataset lineage
- [ ] Add provenance metadata for lineage confidence/source if useful

### 11.4 Backend Lineage Service Tasks

- [ ] Redesign lineage service around the new semantic model
- [ ] Add query modes for upstream, downstream, and neighborhood exploration
- [ ] Add graph filtering options server-side where useful
- [ ] Add recursion/graph traversal safeguards
- [ ] Add performance strategy for large graphs
- [ ] Add async-safe or scalable implementation as needed
- [ ] Add comprehensive lineage service tests

---

## 12. Phase 7 — Lineage UX Redesign Tasks

### 12.1 Core Interaction Model

- [ ] Redesign lineage entry flow around an explicit exploration intent
- [ ] Support selecting an input dataset to see downstream outputs
- [ ] Support selecting an output dataset to see upstream inputs
- [ ] Support full neighborhood exploration mode
- [ ] Add direction controls for upstream/downstream/both
- [ ] Add graph density or detail-level controls

### 12.2 Graph Presentation Tasks

- [ ] Improve node differentiation between datasets, analyses, and internals
- [ ] Add visual treatment for persisted outputs vs ephemeral/code internals
- [ ] Add group/collapse behavior for analysis internals
- [ ] Add expand-into-tabs or expand-into-steps behavior where useful
- [ ] Add legend for graph semantics
- [ ] Add better branch/version badges
- [ ] Add graph-level filters for node and edge types
- [ ] Add hide-intermediate toggle
- [ ] Add show-code-dependencies toggle

### 12.3 Details Panel Tasks

- [ ] Redesign lineage detail panel information hierarchy
- [ ] Show dataset metadata
- [ ] Show producing analysis metadata
- [ ] Show consuming analyses
- [ ] Show branch/version information
- [ ] Show schedule information
- [ ] Show freshness/health/run summary where useful
- [ ] Add “why is this connected?” explanation
- [ ] Add deep links into datasource pages and analysis pages

### 12.4 Exploration Quality Tasks

- [ ] Add graph search
- [ ] Add focus-on-path interaction
- [ ] Add mini-map for large graphs if needed
- [ ] Add saved views or shareable links
- [ ] Add export/snapshot functionality
- [ ] Add empty-state guidance when lineage is absent or partial
- [ ] Add explicit messaging when lineage is inferred rather than exact

### 12.5 Nice-To-Have Lineage Tasks

- [ ] Add historical lineage by run/version
- [ ] Add branch compare view
- [ ] Add analysis-version compare view
- [ ] Add impact analysis / blast radius view
- [ ] Add freshness and failure overlays
- [ ] Add ownership/contact overlays
- [ ] Add anomaly detection for orphaned outputs or duplicate-producing analyses
- [ ] Add AI summary or explanation features if desired later

---

## 13. Phase 8 — Resource Ownership, Collaboration, and Audit Tasks

### 13.1 Ownership Surfacing Tasks

- [ ] Show resource owner on analyses
- [ ] Show resource owner on datasources
- [ ] Show resource owner on UDFs
- [ ] Show last editor or updater where useful
- [ ] Add ownership-based filtering and search

### 13.2 Collaboration Groundwork Tasks

- [ ] Define shared vs personal analysis behavior
- [ ] Define shared vs personal datasource behavior
- [ ] Define shared vs personal UDF behavior
- [ ] Define edit conflict behavior in multi-user mode
- [ ] Define lock/concurrency behavior under authenticated usage

### 13.3 Audit Tasks

- [ ] Add user-aware audit events for auth flows
- [ ] Add user-aware audit events for resource changes
- [ ] Add user-aware audit events for schedule changes
- [ ] Add user-aware audit events for settings changes
- [ ] Add audit visibility strategy for admins

---

## 14. Phase 9 — Settings, Admin, and Operational Tasks

### 14.1 Settings Separation Tasks

- [ ] Separate personal settings from global app settings
- [ ] Gate global settings behind admin permissions
- [ ] Add provider configuration management tasks
- [ ] Add SMTP/email readiness tasks needed for verification and reset flows
- [ ] Add operational visibility for auth provider health if useful

### 14.2 Membership and Admin Tasks

- [ ] Add member management interface
- [ ] Add role assignment interface
- [ ] Add invite/revoke flows in admin areas
- [ ] Add admin audit visibility
- [ ] Add namespace/workspace administration flows consistent with the identity model

---

## 15. Phase 10 — Testing and Verification Tasks

### 15.1 Backend Testing Tasks

- [ ] Add user model tests
- [ ] Add registration tests
- [ ] Add login/logout tests
- [ ] Add password reset tests
- [ ] Add email verification tests
- [ ] Add Google auth tests
- [ ] Add GitHub auth tests
- [ ] Add account linking tests
- [ ] Add permission and access-control tests
- [ ] Add ownership and visibility tests
- [ ] Add lineage semantic correctness tests
- [ ] Add lineage multi-input tests
- [ ] Add lineage branch-aware tests
- [ ] Add lineage upstream/downstream traversal tests

### 15.2 Frontend Testing Tasks

- [ ] Add auth screen tests
- [ ] Add auth store/session tests
- [ ] Add protected-route behavior tests
- [ ] Add account menu/profile/settings tests
- [ ] Add navigation active-state tests
- [ ] Add left-panel behavior tests
- [ ] Add responsive shell tests
- [ ] Add lineage graph filter/detail tests
- [ ] Add lineage detail panel tests
- [ ] Add graph interaction tests

### 15.3 End-To-End Testing Tasks

- [ ] Add register flow E2E
- [ ] Add login flow E2E
- [ ] Add logout flow E2E
- [ ] Add password reset E2E
- [ ] Add Google login E2E
- [ ] Add GitHub login E2E
- [ ] Add provider linking/unlinking E2E
- [ ] Add protected-page access E2E
- [ ] Add role-based access E2E
- [ ] Add lineage correctness regression E2E
- [ ] Add lineage non-ephemeral/default-view regression E2E
- [ ] Add left-panel mobile/responsive E2E

### 15.4 Operational Verification Tasks

- [ ] Validate auth environment setup in local and production-like environments
- [ ] Validate migration behavior on existing data
- [ ] Validate provider callback behavior across environments
- [ ] Validate session persistence and expiry behavior
- [ ] Validate performance of large lineage graphs

---

## 16. Phase 11 — Documentation, Migration, and Rollout Tasks

### 16.1 Internal Documentation Tasks

- [ ] Document auth architecture
- [ ] Document provider setup requirements
- [ ] Document user and permission model
- [ ] Document ownership model
- [ ] Document lineage semantic model
- [ ] Document app-shell navigation model
- [ ] Document migration and rollout steps

### 16.2 User-Facing Documentation Tasks

- [ ] Document registration and login flows
- [ ] Document password reset and account recovery
- [ ] Document connected account management
- [ ] Document lineage interpretation basics
- [ ] Document new navigation model

### 16.3 Migration Tasks

- [ ] Define migration path for legacy deployments
- [ ] Define resource ownership backfill rules
- [ ] Define admin bootstrap flow for first authenticated environment
- [ ] Define guest/local-dev fallback behavior if supported
- [ ] Define rollout order to minimize disruption

---

## 17. Recommended Execution Order

### 17.1 First Wave

1. Resolve identity and permissions decisions
2. Implement core user model and session model
3. Implement email/password registration and login
4. Implement frontend auth state and auth screens
5. Gate sensitive routes/settings

### 17.2 Second Wave

6. Implement Google auth
7. Implement GitHub auth
8. Implement account linking and security/settings UX
9. Add ownership fields and visibility rules

### 17.3 Third Wave

10. Implement new app shell and shared panel framework
11. Adopt the shared shell across analyses, datasources, and lineage
12. Clean up route-specific layout inconsistencies

### 17.4 Fourth Wave

13. Redesign lineage semantic model
14. Fix lineage correctness and recording at the backend
15. Redesign lineage graph UX and detail panels
16. Add lineage advanced features after correctness is solid

### 17.5 Fifth Wave

17. Add invitations, memberships, and admin/member management
18. Add collaboration groundwork and richer audit capabilities
19. Finalize migration docs, rollout docs, and operational readiness

---

## 18. MVP Cut Recommendation

If the overhaul is split into an MVP before full expansion, the MVP should include:

- [ ] User registration with email/password
- [ ] Login/logout/session persistence
- [ ] Google auth
- [ ] GitHub auth
- [ ] Current-user/account menu/profile basics
- [ ] Sensitive settings gating
- [ ] Basic ownership fields on core resources
- [ ] New app shell and shared left-panel system
- [ ] Lineage correctness fix so internal tab flow is not shown as derived datasets by default
- [ ] Improved lineage detail panel and graph filtering

The following can land after MVP:

- [ ] Invitations and full membership management
- [ ] Fine-grained permissions
- [ ] Historical lineage compare
- [ ] Blast radius and impact analysis
- [ ] Saved lineage views
- [ ] Device/session management depth beyond essentials
- [ ] Advanced collaboration and audit experiences

---

## 19. High-Risk Areas To Track

- [ ] Backward compatibility and migration of legacy anonymous usage
- [ ] OAuth account merge edge cases
- [ ] Secure session handling across frontend and backend boundaries
- [ ] Ownership backfill for existing records
- [ ] Preventing lineage overcorrection that hides useful debug detail
- [ ] Performance of richer lineage graphs and recursive traversal
- [ ] App-shell refactor ripple effects across highly custom route layouts

---

## 20. Definition of Ready for Implementation

Before implementation begins on any major epic, confirm:

- [ ] Product decisions for that epic are resolved
- [ ] Scope boundaries are clear
- [ ] Dependencies are understood
- [ ] Required migrations are identified
- [ ] Acceptance criteria are written
- [ ] Test strategy is identified
- [ ] Any rollout or security concerns are explicitly tracked

---

## 21. Immediate Next Planning Step

The next planning artifact after this roadmap should be a **ticketized execution backlog** that converts this roadmap into:

- Epics
- Milestones
- Ordered implementation tasks
- Explicit dependencies
- MVP vs later labeling
- Backend/frontend/test breakdown per task

That backlog should be used as the working implementation plan.
