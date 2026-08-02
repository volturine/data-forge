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

- [Build Preview Checklist](implemented/build-preview-checklist.md) — archived rollout checklist
- [Cancel Build](implemented/cancel-build.md)
- [Dataset Column Descriptions](implemented/dataset-column-descriptions.md)
- [Dataset Descriptions](implemented/dataset-descriptions.md)
- [Distributed Runtime v2](implemented/distributed-runtime-v2.md)
- [Distributed Runtime v2 Progress](implemented/distributed-runtime-v2-progress.md) — archived progress record
- [Duplicate Analysis Tab](implemented/duplicate-analysis-tab.md)
- [Duplicate Analysis](implemented/duplicate-analysis.md)
- [E2E Runtime Baseline](implemented/e2e-runtime-baseline.md) — archived measurement record
- [Engine Lifecycle Alignment](implemented/engine-lifecycle-alignment.md) — superseded design
- [MCP Tool Contract](implemented/mcp-tool-contract.md)
- [Pipeline Compute](implemented/pipeline-compute.md) — superseded design
- [PostgreSQL Backend Support](implemented/postgresql-backend-support.md) — superseded design
- [Runtime Correctness and Architecture Remediation](implemented/runtime-correctness-and-architecture-remediation.md)
- [Scheduling](implemented/scheduling.md) — superseded design
- [Settings Profile Page](implemented/settings-profile-page.md)
- [Shared Boundary Checklist](implemented/shared-boundary-checklist.md) — archived completed audit
- [SQL/Polars Snippet Export](implemented/sql-polars-snippet-export.md)

## Active

- [AI Chat API](active/ai-chat-api.md)
- [Build Length Tracking](active/build-length-tracking.md)
- [Build Preview](active/build-preview.md)
- [Core Product Specification](active/data-forge.md)
- [Docker Release](active/docker-release.md)
- [Documentation Update](active/documentation-update.md)
- [Hot-Path Request Map](active/hot-path-request-map.md)
- [Hugging Face Connection](active/hugging-face-connection.md)
- [Lineage Revamp](active/lineage-revamp.md)
- [New Analysis Creation Flow](active/new-analysis-creation-flow.md)
- [Performance Violation Checklist](active/performance-violation-checklist.md)
- [S3 Storage Support](active/s3-storage-support.md)

## Backlog

- [Analytical Dashboards](backlog/analytical-dashboards.md)
- [Application Shell and Shared Panels](backlog/application-shell.md)
- [Authentication and Identity](backlog/authentication-and-identity.md)
- [Authorization, Ownership, and Collaboration](backlog/authorization-ownership-and-collaboration.md)
- [Feature-overhaul Portfolio](backlog/data-forge-2.md)
- [Horizontal Node Configuration](backlog/horizontal-node-config.md)
- [Kaggle Connection](backlog/kaggle-connection.md)
- [Local Subdomain Serving](backlog/local-subdomain-serving.md)
- [Mobile-first UI](backlog/mobile-first-ui.md)
- [Schedule Descriptions](backlog/schedule-descriptions.md)
- [Snapshot Rollback](backlog/snapshot-rollback.md)
- [Tauri Hybrid Desktop](backlog/tauri-hybrid-desktop.md)
- [Time Since Last Updated](backlog/time-since-last-updated.md)
