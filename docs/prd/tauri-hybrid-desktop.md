# PRD: Tauri Hybrid Desktop App

## Overview

Ship a desktop version of Data-Forge using Tauri while preserving the existing FastAPI + Svelte architecture. The desktop app must support hybrid backend connectivity:

- `local` mode: the desktop app launches a packaged local backend and connects to it over loopback.
- `remote` mode: the desktop app connects to a remotely hosted backend over HTTPS/WSS.
- `auto` mode: the desktop app attempts the configured remote backend first and falls back to local when remote is unavailable and local is permitted.

The frontend remains bundled inside the desktop app. The backend remains a FastAPI service and is not rewritten into Rust.

## Problem Statement

The current product is optimized for browser deployment:

- the frontend uses a static Svelte build,
- API calls assume same-origin relative paths,
- WebSocket URLs are derived from the current browser origin,
- production mode expects FastAPI to serve the built frontend.

That model works well for browser and local-server deployment, but it does not provide a first-class desktop experience. Users who want an installable desktop app currently still depend on manually running a server, and teams that want a managed remote backend do not have a desktop shell that can connect to hosted infrastructure.

The product needs a desktop architecture that:

- works out of the box for local-only users,
- can connect to a hosted backend for team or enterprise use,
- makes backend location explicit to the user,
- preserves the current API, WebSocket, and compute model with minimal behavioral drift.

## Goals

- Ship a Tauri desktop application for macOS, Windows, and Linux.
- Keep the Svelte frontend bundled locally inside the desktop app.
- Preserve the FastAPI backend as the application server and compute orchestration layer.
- Support runtime-selectable backend connectivity: `local`, `remote`, `auto`.
- Allow remote backend configuration without rebuilding the app.
- Keep HTTP, file upload, download, and WebSocket behavior compatible across local and remote modes.
- Make the active backend target visible and understandable to users at all times.
- Preserve existing browser deployment support after the refactor.

## Non-Goals

- Rewriting the FastAPI backend into Rust or Tauri commands.
- Replacing WebSocket streaming with a Tauri-native event bus.
- Loading arbitrary remote frontend pages inside Tauri.
- Adding a data sync product between local and remote environments in this phase.
- Preserving legacy same-origin frontend assumptions if they block a cleaner runtime backend configuration model.

## User Stories

As a local-first user, I can install the desktop app and use it without separately starting a backend process.

**Acceptance Criteria:**
- On first launch in `local` mode, the app starts the packaged backend automatically.
- The app waits for backend readiness before rendering the main application shell as connected.
- The user does not need to open a terminal or manage backend lifecycle manually.

As a hosted-environment user, I can point the desktop app to a remote backend URL and use the product against centrally managed infrastructure.

**Acceptance Criteria:**
- The settings UI allows entering and validating a remote backend base URL.
- The app uses that origin for both HTTP and WebSocket traffic.
- If the remote backend is unavailable, the user sees an explicit error and recovery actions.

As a user with both local and remote options, I can choose how the app connects and understand which backend is active.

**Acceptance Criteria:**
- The app exposes `local`, `remote`, and `auto` connection modes.
- The current resolved backend is visible in the UI.
- Switching modes updates the connection target and resets connection-dependent client state cleanly.

As an admin or distributor, I can preconfigure a desktop build to prefer a known remote backend.

**Acceptance Criteria:**
- The desktop app supports a preconfigured default mode and remote URL.
- User-editable settings may still override defaults unless the build is explicitly locked down in a future phase.

## Product Model

The desktop product has three backend modes:

- `local`: always use the bundled local backend sidecar.
- `remote`: always use the configured remote backend URL.
- `auto`: try remote first, otherwise fall back to local.

The desktop app itself always serves the frontend locally from bundled assets. Only API and WebSocket traffic are routed to either the local or remote backend.

This distinction is intentional:

- the frontend bundle is trusted application code,
- Tauri capabilities remain scoped to bundled local content,
- remote deployment affects only backend communication, not what code is rendered inside the desktop shell.

## Functional Requirements

### Connection Configuration

- The app must store a backend connection mode with values `local`, `remote`, `auto`.
- The app must store a remote backend base URL when remote connectivity is enabled.
- The app must validate the remote backend URL before saving it.
- The app must expose a `Test Connection` action that probes backend readiness and reports success or failure.
- The app must persist connection settings across app restarts.

### Connection Resolution

- In `local` mode, the desktop shell must start the local backend sidecar and connect only to it.
- In `remote` mode, the desktop shell must not start the local backend unless explicitly requested for diagnostics or a future advanced mode.
- In `auto` mode, the connection algorithm must be deterministic:
  1. If a remote URL is configured, probe remote readiness.
  2. If remote readiness succeeds, connect to remote.
  3. If remote readiness fails, start local sidecar and connect to local.
  4. If local startup also fails, present a terminal connection error state.
- The resolved backend target must be surfaced in the UI as a concrete URL or local indicator.

### Frontend Networking

- Frontend API requests must use a runtime-resolved backend origin instead of assuming same-origin relative `/api`.
- Frontend WebSocket URLs must derive from the same resolved backend origin used for HTTP requests.
- The networking layer must preserve existing headers such as namespace, client identity, and session-related headers.
- Upload and download behavior must work identically from the user’s perspective in both local and remote modes.

### Startup and Lifecycle

- On desktop launch, the app must enter a startup state while resolving backend connectivity.
- The app must not present a fully interactive shell until backend readiness succeeds or a clear error state is shown.
- If the local backend sidecar exits unexpectedly, the app must detect this and surface a reconnect/restart path.
- If the remote backend becomes unavailable during use, the app must surface the failure explicitly and avoid silent mode changes.

### Settings and Status UX

- The app must provide a settings area for connection mode and remote URL.
- The app must display current connection mode, current resolved backend, and last connection error.
- The app must warn users before switching backends if the switch will invalidate active sessions, in-memory state, or pending requests.
- The application shell must show a persistent status badge such as `Local`, `Remote`, or `Auto -> Local`.

## Authentication Requirements

The hybrid architecture changes the meaning of authentication depending on backend mode, so auth behavior must be made explicit rather than inferred from the current localhost/browser assumptions.

### Local Mode

- Local mode may continue to use the existing backend session model.
- Local mode may continue to rely on loopback cookie or header-based session behavior as long as it works inside the desktop webview consistently.

### Remote Mode

- Remote mode must support production-safe auth callback configuration and secure cookie/header handling.
- Remote mode must not depend on localhost callback defaults.
- OAuth redirects and frontend callback URLs must become deployment-specific configuration rather than fixed localhost values.

### Desktop OAuth

One of the following approved patterns must be implemented for desktop OAuth:

- browser-based OAuth with deep-link return into the desktop app,
- browser-based OAuth completed on the hosted backend with session establishment propagated back to the desktop app.

The selected pattern must:

- work for both Google and GitHub if those providers remain supported,
- avoid embedding provider secrets in the frontend bundle,
- be documented separately for local and remote deployment paths.

## Technical Design

### High-Level Architecture

The architecture remains split into three layers:

- Tauri shell
- bundled Svelte frontend
- FastAPI backend, either local sidecar or remote host

The Tauri shell is responsible for:

- loading the bundled frontend,
- starting the local backend sidecar when needed,
- waiting for health/readiness,
- exposing a minimal trusted bridge for desktop-only orchestration,
- persisting desktop-specific configuration.

The frontend is responsible for:

- rendering the full application UI,
- selecting and displaying connection mode,
- issuing API and WebSocket calls to the resolved backend origin,
- handling connection failures and reconnect flows.

The backend remains responsible for:

- API routes,
- uploads and downloads,
- compute engine lifecycle,
- WebSocket streams,
- auth/session logic,
- scheduler and background services.

### Frontend Refactor Requirements

The current frontend assumes same-origin networking in two core places:

- [frontend/src/lib/api/client.ts](</Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/lib/api/client.ts:6>)
- [frontend/src/lib/api/websocket.ts](</Users/kripso/Documents/scratchpad/polars-fastapi-svelte/frontend/src/lib/api/websocket.ts:5>)

This must be refactored to a shared runtime network configuration model:

- a single resolved backend origin source,
- a derived API base,
- a derived WebSocket base,
- a startup-safe access pattern so networking does not begin before backend resolution is complete.

The browser deployment must continue to work after this refactor. Browser mode may still default to same-origin behavior when no desktop runtime configuration is present.

### Desktop Shell Requirements

The Tauri shell must:

- package the frontend build output,
- package a backend sidecar binary for each target platform,
- start and monitor the backend sidecar in `local` and `auto -> local` modes,
- expose a readiness polling mechanism before handing control to the connected app shell,
- terminate the sidecar cleanly on desktop app shutdown.

The shell must not expose broad filesystem, shell, or process capabilities to arbitrary runtime content. Only the bundled frontend should be able to invoke the limited desktop bridge.

### Backend Packaging

The backend must be packaged as a standalone executable per platform. The packaging strategy must preserve:

- FastAPI HTTP server behavior,
- WebSocket endpoints,
- multiprocessing compute engine startup,
- background loops for cleanup and scheduling,
- production static-serving behavior for non-Tauri deployments.

The backend already contains frozen-runtime handling and frontend build path resolution logic in [backend/main.py](</Users/kripso/Documents/scratchpad/polars-fastapi-svelte/backend/main.py:31>). That support should be treated as a starting point, not final proof that packaging is production-ready.

### Remote Backend Requirements

- Remote mode must require a fully qualified backend origin.
- Production remote mode must use HTTPS and WSS.
- Remote backend must expose readiness endpoints compatible with desktop connection testing.
- Remote backend deployments must support any required CORS, cookie, and auth policy needed for a desktop webview client.

### Data and Environment Boundaries

Local and remote modes are distinct execution environments.

This phase does not introduce synchronization between them. Therefore:

- local uploads remain local,
- remote uploads remain remote,
- local datasets and remote datasets are separate unless a later sync product is defined,
- the UI must make the current environment clear before users perform actions with storage or compute consequences.

## Security and Validation

- The desktop app must not load arbitrary remote frontend content inside Tauri.
- Tauri capabilities must be granted only to bundled local frontend assets.
- The remote backend URL validator must reject malformed, unsupported, or unsafe schemes.
- Local sidecar networking must bind to loopback only.
- Remote production connectivity must require TLS.
- Secrets must remain on the backend or in desktop-managed secure storage where applicable, never in the frontend bundle.
- Mode switching must not silently redirect sensitive operations to a different backend target.

## Risks

- OAuth is significantly more complex in a desktop + remote model than in a browser + localhost model.
- Backend packaging across macOS, Windows, and Linux adds release engineering overhead.
- Session behavior may differ between loopback local mode and remote hosted mode.
- Data locality becomes a user-facing concern once remote execution is supported.
- If local and remote backends diverge operationally, users may encounter environment-specific behavior that feels inconsistent unless the UI explains it clearly.

## Migration

The migration should be staged to reduce risk and preserve browser functionality.

### Stage 1: Runtime Network Configuration

- Replace hardcoded same-origin API assumptions with a runtime-resolved backend origin.
- Preserve existing browser deployment behavior.
- Add tests for HTTP and WebSocket URL resolution.

### Stage 2: Tauri Local Mode

- Introduce Tauri shell and bundled frontend.
- Package and launch backend sidecar.
- Support local desktop mode only.

### Stage 3: Remote Mode

- Add remote backend settings UI.
- Add remote readiness testing.
- Support remote HTTP and WebSocket connectivity.

### Stage 4: Auto Mode and Connection UX

- Add deterministic remote-first fallback logic.
- Add startup resolution UI and connection badges.
- Add reconnect and switch-backend flows.

### Stage 5: Auth Hardening and Distribution

- Complete desktop OAuth/deep-link implementation.
- Finalize signing, notarization, and cross-platform packaging details.

## Rollout Plan

- Deliver runtime backend configurability behind a controlled implementation branch.
- Verify browser deployment remains stable before introducing Tauri packaging.
- Release desktop local mode first as the lowest-risk user-facing milestone.
- Release remote mode after auth and connection-state handling are proven.
- Release auto mode only after failure states and backend switching are fully explicit and deterministic.

## Acceptance Criteria

- A Tauri desktop app can be built and launched on supported target platforms.
- In `local` mode, the app starts a packaged backend automatically and becomes usable without manual server startup.
- In `remote` mode, the app connects to a configured hosted backend and core API plus WebSocket features function correctly.
- In `auto` mode, the app deterministically resolves to remote or local and reports the resolved target to the user.
- The frontend no longer hardcodes same-origin backend assumptions.
- Browser deployment remains functional after the networking refactor.
- Backend switching is user-visible, recoverable, and never silent.
- Auth configuration supports non-localhost production deployment paths.

## Open Questions

- Should remote mode be available in all desktop builds or only selected distributions?
- Should local mode and remote mode use the same auth UX, or should local mode allow a simpler path?
- Should backend selection be app-global, profile-specific, or workspace-specific?
- Should enterprise builds support policy-managed locked remote endpoints in a later phase?
- Should the app ever offer explicit import/export or sync between local and remote environments, or should those remain intentionally separate?
