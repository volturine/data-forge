# Product and Architecture Documentation

> **Portfolio audited 2026-08-02.** Each document is grouped by its current role, so the repository tree itself distinguishes shipped work, active work, future work, reference material, historical records, and performance evidence.

```
docs/prd/
├── implemented/  # shipped feature PRDs and completed remediation
├── active/       # work in progress or partially implemented features
├── backlog/      # approved future work and product decisions
├── performance/  # runtime measurements, hot paths, and rebaseline work
├── reference/    # architecture/contracts that describe the current system
└── historical/   # superseded plans retained for context
```

## Implemented

- [Cancel Build](implemented/cancel-build.md)
- [Dataset Column Descriptions](implemented/dataset-column-descriptions.md)
- [Dataset Descriptions](implemented/dataset-descriptions.md)
- [Duplicate Analysis Tab](implemented/duplicate-analysis-tab.md)
- [Duplicate Analysis](implemented/duplicate-analysis.md)
- [Runtime Correctness and Architecture Remediation](implemented/runtime-correctness-and-architecture-remediation.md)
- [Settings Profile Page](implemented/settings-profile-page.md)
- [SQL/Polars Snippet Export](implemented/sql-polars-snippet-export.md)

## Active

- [AI Chat API](active/ai-chat-api.md)
- [Build Length Tracking](active/build-length-tracking.md)
- [Build Preview](active/build-preview.md)
- [Core Product Specification](active/data-forge.md)
- [Docker Release](active/docker-release.md)
- [Documentation Update](active/documentation-update.md)
- [Hugging Face Connection](active/hugging-face-connection.md)
- [Lineage Revamp](active/lineage-revamp.md)
- [New Analysis Creation Flow](active/new-analysis-creation-flow.md)
- [S3 Storage Support](active/s3-storage-support.md)

## Performance

- [E2E Runtime Baseline](performance/e2e-runtime-baseline.md)
- [Hot-Path Request Map](performance/hot-path-request-map.md)
- [Performance Violation Checklist](performance/violation-checklist.md)

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

## Reference

- [Distributed Runtime v2 Progress](reference/distributed-runtime-v2-progress.md)
- [Distributed Runtime v2](reference/distributed-runtime-v2.md)
- [MCP Tool Contract](reference/mcp-tool-contract.md)
- [Shared Boundary Checklist](reference/shared-boundary-checklist.md)

## Historical

- [Build Preview Checklist](historical/build-preview-checklist.md)
- [Engine Lifecycle Alignment](historical/engine-lifecycle-alignment.md)
- [Pipeline Compute](historical/pipeline-compute.md)
- [PostgreSQL Backend Support](historical/postgresql-backend-support.md)
- [Scheduling](historical/scheduling.md)
