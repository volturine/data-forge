Master Task List

- tasks/tasks-data-analysis-platform.md - Contains overview, dependency graph, team allocation guide, and progress tracking

Backend Track (5 folders)

┌─────────────────────┬───────────────────────────────────────┬───────────────────────────────────┐
│       Folder        │                 Tasks                 │     Can Run In Parallel With      │
├─────────────────────┼───────────────────────────────────────┼───────────────────────────────────┤
│ backend-core/       │ 1.0 - Config, DB, migrations          │ frontend-infrastructure/          │
├─────────────────────┼───────────────────────────────────────┼───────────────────────────────────┤
│ backend-datasource/ │ 2.0 - File upload, schema extraction  │ backend-analysis/, all frontend   │
├─────────────────────┼───────────────────────────────────────┼───────────────────────────────────┤
│ backend-analysis/   │ 3.0 - Analysis CRUD, pipeline storage │ backend-datasource/, all frontend │
├─────────────────────┼───────────────────────────────────────┼───────────────────────────────────┤
│ backend-compute/    │ 4.0 - Polars subprocess engine        │ All frontend                      │
├─────────────────────┼───────────────────────────────────────┼───────────────────────────────────┤
│ backend-results/    │ 5.0 - Result storage, export          │ All frontend                      │
└─────────────────────┴───────────────────────────────────────┴───────────────────────────────────┘

Frontend Track (7 folders)
Folder: frontend-infrastructure/
Tasks: 6.0 - Types, API client, TanStack Query
Can Run In Parallel With: backend-core/

────────────────────────────────────────

Folder: frontend-api/
Tasks: 7.0 - API client functions
Can Run In Parallel With: All backend

────────────────────────────────────────

Folder: frontend-stores/
Tasks: 8.0-9.0 - Schema calculator, Svelte stores
Can Run In Parallel With: frontend-viewers/, frontend-pipeline/

────────────────────────────────────────

Folder: frontend-gallery/
Tasks: 10.0-11.0, 16.0 - Gallery, wizard, data sources
Can Run In Parallel With: frontend-viewers/, frontend-pipeline/

────────────────────────────────────────

Folder: frontend-viewers/
Tasks: 12.0 - DataTable, SchemaViewer, Charts
Can Run In Parallel With: frontend-gallery/, frontend-pipeline/

────────────────────────────────────────

Folder: frontend-pipeline/
Tasks: 13.0-14.0 - Step configs, pipeline builder
Can Run In Parallel With: frontend-viewers/

────────────────────────────────────────

Folder: frontend-editor/
Tasks: 15.0, 17.0 - Editor page, UX polish
Can Run In Parallel With: - (needs all above)
Integration (1 folder)

┌──────────────────────┬──────────────────────────────────┐
│        Folder        │              Tasks               │
├──────────────────────┼──────────────────────────────────┤
│ integration-testing/ │ 18.0-19.0 - Tests, docs, cleanup │
└──────────────────────┴──────────────────────────────────┘

Key Features

1. Parallel Work: Backend and Frontend tracks can proceed simultaneously
2. Clear Dependencies: Each folder lists what it depends on and what it can parallelize with
3. Detailed Sub-tasks: Each file has granular checkbox items (200+ total sub-tasks)
4. Completion Criteria: Each module has specific completion requirements
5. Team Allocation Guide: Suggestions for 2-4 developer teams
6. Progress Tracking: Visual table in master file to track overall progress

Start with backend-core/ and frontend-infrastructure/ in parallel, then branch out from there!