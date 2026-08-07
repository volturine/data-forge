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

- [Build Length Tracking](implemented/build-length-tracking.md)
- [Build Preview Checklist](implemented/build-preview-checklist.md) — archived rollout checklist
- [Build Preview](implemented/build-preview.md)
- [Cancel Build](implemented/cancel-build.md)
- [Docker Release](implemented/docker-release.md)
- [Dataset Column Descriptions](implemented/dataset-column-descriptions.md)
- [Dataset Descriptions](implemented/dataset-descriptions.md)
- [Core Product Specification](implemented/data-forge.md)
- [Distributed Runtime v2](implemented/distributed-runtime-v2.md)
- [Distributed Runtime v2 Progress](implemented/distributed-runtime-v2-progress.md) — archived progress record
- [Documentation Update](implemented/documentation-update.md)
- [Duplicate Analysis Tab](implemented/duplicate-analysis-tab.md)
- [Duplicate Analysis](implemented/duplicate-analysis.md)
- [E2E Runtime Baseline](implemented/e2e-runtime-baseline.md) — current five-run measurement record
- [Engine Lifecycle Alignment](implemented/engine-lifecycle-alignment.md) — superseded design
- [Hot-Path Ownership Map](implemented/hot-path-ownership-map.md) — current product-path ownership contract
- [Hot-Path Profiling Record](implemented/hot-path-request-map.md) — direct timing, request, and occupancy evidence
- [MCP Tool Contract](implemented/mcp-tool-contract.md)
- [New Analysis Creation Flow](implemented/new-analysis-creation-flow.md)
- [Performance Stability Gate](implemented/performance-stability-gate.md) — current repeated-run safeguards and evidence
- [Performance Regression Investigation](implemented/performance-regression-investigation.md) — optimized 410.93s baseline and clean RustFS warning gate
- [Pipeline Compute](implemented/pipeline-compute.md) — superseded design
- [PostgreSQL Backend Support](implemented/postgresql-backend-support.md) — superseded design
- [Runtime Correctness and Architecture Remediation](implemented/runtime-correctness-and-architecture-remediation.md)
- [Schedule Descriptions](implemented/schedule-descriptions.md)
- [Scheduling](implemented/scheduling.md) — superseded design
- [Settings Profile Page](implemented/settings-profile-page.md)
- [Shared Boundary Checklist](implemented/shared-boundary-checklist.md) — archived completed audit
- [SQL/Polars Snippet Export](implemented/sql-polars-snippet-export.md)
- [S3 Storage Support](implemented/s3-storage-support.md) — per-namespace object-store buckets

## Active

- [Lineage Revamp](active/lineage-revamp.md)

## Backlog

- [Analytical Dashboards](backlog/analytical-dashboards.md)
- [AI Chat API](backlog/ai-chat-api.md)
- [Application Shell and Shared Panels](backlog/application-shell.md)
- [Authentication and Identity](backlog/authentication-and-identity.md)
- [Authorization, Ownership, and Collaboration](backlog/authorization-ownership-and-collaboration.md)
- [Build Observability](backlog/build-observability.md)
- [Containerized Polars Engines](backlog/containerized-polars-engines.md)
- [Feature-overhaul Portfolio](backlog/data-forge-2.md)
- [Horizontal Node Configuration](backlog/horizontal-node-config.md)
- [Kaggle Connection](backlog/kaggle-connection.md)
- [Local Subdomain Serving](backlog/local-subdomain-serving.md)
- [Mobile-first UI](backlog/mobile-first-ui.md)
- [Snapshot Rollback](backlog/snapshot-rollback.md)
- [Tauri Hybrid Desktop](backlog/tauri-hybrid-desktop.md)
- [Time Since Last Updated](backlog/time-since-last-updated.md)
