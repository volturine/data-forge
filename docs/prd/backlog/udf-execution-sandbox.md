# PRD: UDF Execution Sandbox

> **Status:** Backlog — identified by the 2026-08 codebase audit.
> **Portfolio:** [PRD index](../README.md)

## Summary

User-defined functions (UDFs) currently execute worker-side via `exec` with a substring blacklist as the only guard (`packages/worker/operations/with_columns.py`). Polars' namespace exposes file and network I/O, so the blacklist is not a sandbox: any UDF author can read or exfiltrate data, reach the network, or interfere with the host. This PRD replaces the pseudo-sandbox with a real execution boundary.

## Problem

- `exec` runs arbitrary Python with full access to the worker process, its environment, credentials, and the object store.
- The blacklist is trivially bypassed (string concatenation, attribute traversal, imports).
- The backend validates UDF code syntax only; ownership-less UDF CRUD plus MCP exposure means broad write access to executable code.

## Decisions required before implementation

- [ ] Decide whether UDFs remain a feature at all, given pipelines cover most transforms.
- [ ] If kept: decide between (a) running UDFs only inside the containerized engine boundary with no shared filesystem/network egress, or (b) a restricted embedded interpreter (e.g., a WASM or subprocess jail with resource limits).
- [ ] Decide whether UDF authoring is administrator-only.

## Scope

### Execution boundary

- [ ] Execute UDFs in an isolated context: no host filesystem access, no network egress except explicitly injected handles, capped CPU/memory/time.
- [ ] Remove `exec` from the request path entirely; reject UDFs that cannot run under the new boundary.
- [ ] Surface clear validation errors for unsupported constructs instead of silent blacklist matches.

### Governance

- [ ] Restrict UDF create/update/delete to authorized roles once [Authorization, Ownership, and Collaboration](authorization-ownership-and-collaboration.md) lands.
- [ ] Audit-log UDF executions with author identity and step reference.

## Non-goals

- Making the current blacklist stricter — it cannot be made safe.
- Supporting arbitrary third-party Python packages inside UDFs.

## Success criteria

- A malicious UDF (file read, network call, environment scrape) fails closed under the new boundary.
- Existing legitimate UDF workloads pass unchanged.
