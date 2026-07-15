# PRD Portfolio Status Index

This index is the fastest way to understand which PRDs reflect current product truth, which are backlog, and which are now historical.

## Status legend

- **Implemented** — shipped in the current product/runtime
- **Partial** — some meaningful implementation exists, but the PRD still contains unshipped scope
- **Not implemented** — backlog / design intent only
- **Superseded** — historical design that should not be used as current implementation truth
- **Reference** — maintained as an implementation/maintainer reference rather than a future feature spec

## Current truth summary

- The supported metadata/runtime backend is **PostgreSQL**.
- The distributed runtime v2 (durable Postgres-backed builds, scheduler, and websocket state) is **shipped**.
- Build preview, build cancellation, settings-under-profile, SQL/Polars snippet export, datasource descriptions, and column descriptions are shipped.
- Several older architecture PRDs still exist for history, but they describe pre-runtime-v2 behavior and should not be read as live truth.

## PRD status matrix

| PRD | Status | Current truth / note | Next action |
|---|---|---|---|
| `ai-chat-api.md` | Partial | Multi-provider AI settings/chat support exists; deeper unification remains | Keep as backlog/reference |
| `analytical-dashboards.md` | Not implemented | No shipped dashboard runtime layer | Keep as backlog |
| `build-length-tracking.md` | Partial | Duration/timing data exists; dedicated duration UX/trends/alerts do not | Keep as backlog |
| `build-preview-checklist.md` | Superseded | Historical rollout checklist for build preview | Keep only as historical companion |
| `build-preview.md` | Partial | Live build preview is shipped; some aspirational subfeatures remain backlog | Keep and trim against current truth over time |
| `cancel-build.md` | Implemented | Build cancellation is shipped; detailed endpoint/process language is partly historical | Keep as implemented feature record |
| `data-forge-2.md` | Not implemented | Future overhaul roadmap, not current product state | Keep as roadmap |
| `data-forge.md` | Partial | Still useful as product vision, but some runtime details are historical | Keep, continue truth cleanup |
| `dataset-column-descriptions.md` | Implemented | Column description read/write flows exist | Keep as implemented feature record |
| `dataset-descriptions.md` | Implemented | Datasource description flows are shipped | Keep as implemented feature record |
| `distributed-runtime-v2-progress.md` | Reference | Best high-level runtime progress tracker, though some path references are older | Keep as runtime reference |
| `distributed-runtime-v2.md` | Partial | Core durable Postgres runtime is shipped; remaining work is follow-up polish/observability | Keep as architecture record + backlog |
| `documentation-update.md` | Partial | Docs surface now exists, but cleanup/truth alignment remains | Keep as docs backlog |
| `duplicate-analysis-tab.md` | Implemented | Tab duplication exists | Keep as implemented feature record |
| `duplicate-analysis.md` | Implemented | Whole-analysis duplication exists | Keep as implemented feature record |
| `engine-lifecycle-alignment.md` | Superseded | Engine lifecycle alignment is now historical; the Docker-native swap was completed elsewhere | Keep as historical lifecycle rationale |
| `horizontal-node-config.md` | Not implemented | Horizontal scaling config remains backlog | Keep as backlog |
| `hugging-face-connection.md` | Not implemented | Hugging Face integration remains backlog | Keep as backlog |
| `kaggle-connection.md` | Not implemented | Kaggle integration remains backlog | Keep as backlog |
| `lineage-revamp.md` | Not implemented | Lineage revamp remains backlog | Keep as backlog |
| `local-subdomain-serving.md` | Not implemented | Local subdomain serving is not the current dev model | Keep as backlog |
| `mcp-tool-contract.md` | Not implemented | MCP tool contract remains backlog | Keep as backlog |
| `mobile-first-ui.md` | Not implemented | Mobile-first UI remains backlog | Keep as backlog |
| `pipeline-compute.md` | Superseded | Describes the earlier multiprocessing engine architecture; now superseded by the durable runtime | Keep as historical architecture record |
| `s3-storage-support.md` | Not implemented | S3 storage support remains backlog | Keep as backlog |
| `schedule-descriptions.md` | Not implemented | Schedule descriptions remain backlog | Keep as backlog |
| `scheduling.md` | Superseded | Describes the earlier in-process scheduler; now superseded by the dedicated scheduler service | Keep as historical architecture record |
| `settings-profile-page.md` | Implemented | Profile/settings consolidation is shipped | Keep as implemented feature record |
| `shared-boundary-checklist.md` | Reference | Package boundary checklist; mostly historical after package reshaping | Keep as reference |
| `snapshot-rollback.md` | Not implemented | Snapshot rollback is not a shipped feature | Keep as backlog |
| `sql-polars-snippet-export.md` | Implemented | SQL/Polars snippet export is shipped | Keep as implemented feature record |
| `tauri-hybrid-desktop.md` | Not implemented | Tauri hybrid desktop remains backlog | Keep as backlog |
| `time-since-last-updated.md` | Not implemented | Time-since-last-updated remains backlog | Keep as backlog |
