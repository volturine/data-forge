# Product and Architecture Documentation

> **Portfolio audited 2026-08-02.** The PRD tree communicates only delivery status: shipped work, work in progress, and future work. Implemented includes archived checklists and superseded designs as completion context.

```
docs/prd/
├── implemented/  # shipped features, completed architecture, and archived completion context
├── active/       # work in progress, partial features, and active performance investigation
└── backlog/      # approved future work and product decisions
```

The root [README](../../README.md) is the human-facing project overview. [AGENTS.md](../../AGENTS.md) defines repository workflow and the documentation maintenance rule. PRDs carry detailed feature requirements only.

## Implemented

- [AI Chat API](implemented/ai-chat-api.md) — OpenRouter and Ollama for chat and the AI step
- [Build Length Tracking](implemented/build-length-tracking.md)
- [Capacity-First Runtime Optimization](implemented/capacity-first-runtime-optimization.md) — runtime contracts, scale policy, and readiness gates
- [Build Preview](implemented/build-preview.md)
- [Containerized Polars Engines](implemented/containerized-polars-engines.md) — Docker-native execution, lifecycle, capacity, recovery, and reconciliation
- [Cancel Build](implemented/cancel-build.md)
- [Docker Release](implemented/docker-release.md)
- [Dataset Column Descriptions](implemented/dataset-column-descriptions.md)
- [Dataset Descriptions](implemented/dataset-descriptions.md)
- [Core Product Specification](implemented/data-forge.md) — includes analysis UDF editing and large namespace/compute worker dialogs
- [Distributed Runtime v2](implemented/distributed-runtime-v2.md)
- [Duplicate Analysis Tab](implemented/duplicate-analysis-tab.md)
- [Duplicate Analysis](implemented/duplicate-analysis.md)
- [E2E Runtime Baseline](implemented/e2e-runtime-baseline.md) — superseded five-run baseline retained for comparison
- [Engine Lifecycle Alignment](implemented/engine-lifecycle-alignment.md) — superseded design
- [Hot-Path Ownership Map](implemented/hot-path-ownership-map.md) — current product-path ownership contract
- [Hot-Path Profiling Record](implemented/hot-path-request-map.md) — direct timing, request, and occupancy evidence
- [MCP Tool Contract](implemented/mcp-tool-contract.md) — typed registry and `MCPRouter` onboarding
- [Namespace Credential Management](implemented/namespace-credential-management.md) — provisioning, encrypted storage, and scoped worker access
- [New Analysis Creation Flow](implemented/new-analysis-creation-flow.md)
- [Performance Stability Gate](implemented/performance-stability-gate.md) — current repeated-run safeguards and evidence
- [Performance Regression Investigation](implemented/performance-regression-investigation.md) — optimized 410.93s baseline and clean RustFS warning gate
- [Pipeline Compute](implemented/pipeline-compute.md) — superseded design
- [PostgreSQL Backend Support](implemented/postgresql-backend-support.md) — superseded design
- [Runtime Correctness and Architecture Remediation](implemented/runtime-correctness-and-architecture-remediation.md)
- [Schedule Descriptions](implemented/schedule-descriptions.md)
- [Scheduling](implemented/scheduling.md) — superseded design
- [Settings Profile Page](implemented/settings-profile-page.md)
- [SQL/Polars Snippet Export](implemented/sql-polars-snippet-export.md)
- [S3 Storage Support](implemented/s3-storage-support.md) — per-namespace object-store buckets

## Active

None.

## Backlog

- [Analytical Dashboards](backlog/analytical-dashboards.md)
- [Application Shell and Shared Panels](backlog/application-shell.md)
- [Authentication and Identity](backlog/authentication-and-identity.md)
- [Authorization, Ownership, and Collaboration](backlog/authorization-ownership-and-collaboration.md)
- [Build Observability](backlog/build-observability.md)
- [Feature-overhaul Portfolio](backlog/data-forge-2.md)
- [Frontend Component Decomposition](backlog/frontend-component-decomposition.md) — split components over ~800 lines; folds in audit a11y/timer/enum-drift findings
- [Horizontal Node Configuration](backlog/horizontal-node-config.md)
- [Kaggle Connection](backlog/kaggle-connection.md)
- [Local Subdomain Serving](backlog/local-subdomain-serving.md)
- [Mobile-first UI](backlog/mobile-first-ui.md)
- [Namespace Credential Lifecycle](backlog/namespace-credential-lifecycle.md) — rotation, revocation, expiry, and audit
- [Snapshot Rollback](backlog/snapshot-rollback.md)
- [Tauri Hybrid Desktop](backlog/tauri-hybrid-desktop.md)
- [2,000-User Capacity Validation](backlog/two-thousand-user-capacity-validation.md) — interactive, compute, and resilience profiles with SLOs
- [UDF Execution Sandbox](backlog/udf-execution-sandbox.md) — replace the ineffective UDF `exec` blacklist with a real execution boundary
