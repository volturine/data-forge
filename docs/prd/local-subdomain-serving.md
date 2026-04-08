# PRD: Local Subdomain Serving
 
## Overview
 
Serve the Data-Forge application under a local subdomain (e.g., `dataforge.localhost`) instead of `localhost:8000`, providing a cleaner URL, implicit port hiding, and better cookie/CORS isolation for local development and single-machine deployments.
 
## Problem Statement
 
Data-Forge currently runs on `localhost:8000` (backend) and `localhost:5173` (frontend dev server). This creates minor but persistent friction:
 
- **Port numbers are ugly and forgettable**: Users must remember port 8000.
- **Cookie scope**: Cookies scoped to `localhost` can conflict with other local services.
- **CORS complexity**: Frontend and backend on different ports require CORS configuration.
- **Production parity**: Production deployments use a proper domain; local development should approximate this.
- **Multi-instance conflicts**: Running two Data-Forge instances requires different ports.
 
### Current State
 
| Concern | Status |
|---------|--------|
| Backend URL | `http://localhost:8000` |
| Frontend dev URL | `http://localhost:5173` |
| Production serving | Backend serves static frontend build |
| CORS | Configured for both ports |
| Custom domain | ❌ Not supported locally |
 
## Goals
 
| # | Goal | Success Metric |
|---|------|----------------|
| G-1 | Access via `dataforge.localhost` | App accessible at `http://dataforge.localhost` (port 80) |
| G-2 | Zero external dependency | No cloud DNS or external service required — works offline |
| G-3 | Optional — not required | Users can still access via `localhost:8000` if they prefer |
| G-4 | Development mode support | `just dev` optionally serves on subdomain |
 
## Non-Goals
 
- HTTPS for local development (use a reverse proxy like Caddy if needed)
- Public DNS or tunnel (e.g., ngrok, Cloudflare Tunnel)
- Multi-tenant subdomains (e.g., `namespace.dataforge.localhost`)
- Automatic `/etc/hosts` modification (document as manual step)
 
## User Stories
 
### US-1: Access Data-Forge via Local Subdomain
 
> As a user, I want to access Data-Forge at `http://dataforge.localhost` instead of `http://localhost:8000`.
 
**Acceptance Criteria:**
 
1. A lightweight reverse proxy (Caddy or nginx config provided) maps `dataforge.localhost:80` → `localhost:8000`.
2. Modern browsers resolve `*.localhost` to `127.0.0.1` natively (Chrome, Firefox, Edge — per RFC 6761).
3. For browsers/OS that don't resolve `*.localhost`, documentation explains adding `127.0.0.1 dataforge.localhost` to `/etc/hosts` (or Windows equivalent).
4. The app's CORS configuration includes `http://dataforge.localhost`.
5. API calls from the frontend work without port specification.
 
### US-2: Use Subdomain in Development
 
> As a developer, I want `just dev` to optionally proxy through a local subdomain.
 
**Acceptance Criteria:**
 
1. `just dev-subdomain` starts both servers with a local Caddy proxy.
2. Caddy config auto-generated from env vars: `LOCAL_DOMAIN=dataforge.localhost`.
3. Frontend dev server (Vite) configured to accept requests from the subdomain.
4. Hot-reload works through the proxy.
 
### US-3: Production Single-Machine Deployment
 
> As a self-hoster, I want my Data-Forge instance accessible at a clean local URL.
 
**Acceptance Criteria:**
 
1. Docker Compose includes an optional Caddy service for subdomain routing.
2. `LOCAL_DOMAIN` env var configures the subdomain (default: `dataforge.localhost`).
3. Caddy handles both HTTP and optional automatic HTTPS (with local CA for `.localhost`).
 
## Technical Design
 
### Approach: Caddy Reverse Proxy
 
Caddy is chosen for its simplicity — zero-config HTTPS, single binary, declarative config:
 
```Caddyfile
{
    auto_https off
}
 
http://dataforge.localhost {
    reverse_proxy localhost:8000
}
```
 
For development with frontend dev server:
 
```Caddyfile
http://dataforge.localhost {
    handle /api/* {
        reverse_proxy localhost:8000
    }
    handle {
        reverse_proxy localhost:5173
    }
}
```
 
### Configuration
 
| Variable | Default | Description |
|----------|---------|-------------|
| `LOCAL_DOMAIN` | `dataforge.localhost` | Subdomain for local access |
| `LOCAL_PROXY_ENABLED` | `false` | Enable Caddy proxy on `just dev` |
 
### Justfile Commands
 
```just
dev-subdomain:
    caddy run --config Caddyfile.dev &
    just dev
 
stop-subdomain:
    caddy stop
```
 
### Docker Compose Addition
 
```yaml
services:
  caddy:
    image: caddy:2-alpine
    profiles: ["subdomain"]
    ports:
      - "80:80"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
    depends_on:
      - app
```
 
### Browser Compatibility
 
| Browser | `*.localhost` resolves natively? |
|---------|-------------------------------|
| Chrome 93+ | ✅ Yes |
| Firefox 84+ | ✅ Yes |
| Edge (Chromium) | ✅ Yes |
| Safari | ⚠️ Requires `/etc/hosts` entry |
| curl | ⚠️ Depends on system resolver |
 
### CORS Update
 
Add `LOCAL_DOMAIN` to CORS origins in `core/config.py`:
 
```python
cors_origins: list[str] = [
    "http://localhost:3000",
    "http://localhost:5173",
    f"http://{settings.local_domain}",
]
```
 
## File Deliverables
 
| File | Purpose |
|------|---------|
| `Caddyfile` | Production proxy config |
| `Caddyfile.dev` | Development proxy config (frontend + backend) |
| Updated `docker-compose.yml` | Caddy service with `subdomain` profile |
| Updated `Justfile` | `dev-subdomain` and `stop-subdomain` commands |
| Updated CORS config | Include `LOCAL_DOMAIN` origin |
 
## Risks
 
| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Safari/curl doesn't resolve `*.localhost` | Medium | Low | Document `/etc/hosts` workaround |
| Port 80 conflict with existing services | Medium | Low | Make port configurable; document alternative |
| Caddy dependency adds complexity | Low | Low | Caddy is optional — direct port access always works |
 
## Acceptance Criteria
 
- [ ] `http://dataforge.localhost` serves the app when Caddy proxy is running
- [ ] `http://localhost:8000` continues to work (no regression)
- [ ] `just dev-subdomain` starts the full stack with proxy
- [ ] Docker Compose `--profile subdomain` includes Caddy
- [ ] CORS accepts requests from the configured subdomain
- [ ] Documentation covers `/etc/hosts` setup for Safari/curl
- [ ] Hot-reload works through the proxy in development
 