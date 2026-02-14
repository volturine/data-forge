# bugs.md can change while you work read it before saing a bug/tast is done if clarifications were added

# whilst working on features and bugs you may think of improvements and new features worhi of considerations.. you may add them to docs/propositions.md i'll wet them if i like them and them here

main point dont stop until you have tested these with python tests for all backend.. and verified frontend does make equvalient calls and all datatypes are correct

---

consolidated requirements (source: original taskfile + bugs/spec clarifications)

1. Visualization nodes
   - Provide core chart/graph node types.
   - Charts are view-only nodes: they consume input data, render inline visuals, and do not alter DAG data flow.
   - Chart nodes must be insertable anywhere in the pipeline (same behavior as inline preview).
   - Use Svelte + D3 patterns (reference: https://datavisualizationwithsvelte.com/).

2. Notification node
   - Support per-row execution with configurable input column(s) and output status column.
   - Support SMTP and Telegram in node config.
   - Allow using global defaults or node-level overrides.

3. AI node
   - AI node is a predefined UDF wrapper for chat APIs (OpenAI/Ollama/custom endpoint).
   - Support one or more input columns and prompt templates/literals.
   - Output must be written to a new result column per row.

4. Analysis tab dependencies (same analysis vs external)
   - Within the same analysis, tabs may use other tabs as direct lazyframe inputs.
   - Cross-analysis usage must use exported datasources.
   - Building a tab that depends on another tab in the same analysis must execute upstream + downstream logic and show all steps in build logs.
   - Building a tab that depends on an export from another analysis or the same analysis must execute only the downstream logic and therefore only show downstream steps in build logs since no upstream logic is executed as it uses the exported datasource and not the lazyframe of the other tab.

5. Export/output model
   - Every analysis tab has an output/export node by default.
   - Every output is materialized as an Iceberg table.
   - `is_hidden` controls visibility to other analyses only (not whether export exists).
   - `is_hidden` must not disable column stats, healthchecks, schedules, lineage, or same-analysis tab dependencies.
   - Output node includes: export name (alias of datasource name in datasources tab), notification settings, schedule settings, hidden toggle, manual build action.

6. Scheduling
   - Schedules are bound to output datasets (not generic analysis-level intent).
   - Scheduled runs produce build records and timetravel snapshots when export is expected (which is always) as we are building datasets.
   - Support dependency chains:
     - Cron-based runs
     - Run B after A completes
     - Optional event trigger (run when dataset A updates)
   - Schedule UI requirements:
     - Reusable schedule component in datasource panel, analysis panel in export node, schedules page, and lineage panel.
     - Truncated long names, expandable/editable rows.

7. Lineage page
   - Default layout is horizontal; include explicit layout controls.
   - Canvas should fill available workspace area (minus headers).
   - Support panning/drag navigation of the canvas.
   - Left panel must not be occluded by nodes; either reserve canvas space after panel or keep panel always topmost.
   - Schedules panel should open from the left when datasource nodes are selected.

8. Builds and execution observability
   - Step timeline must show human-meaningful step labels (not opaque IDs only).
   - Build detail must identify schedule-triggered executions.
   - Builds table should include output target column.
   - Improve filters and execution flow readability.

9. Datasource page
   - Add direct datasource download action.
   - Show clear `is_hidden` indicator in datasource settings.
   - `is_hidden` filtering must work reliably.
   - If datasource changes, close/reset any open column-stats panel.

10. Column stats UX
    - Clicking a column triggers stats computation.
    - Show stats in a bottom panel with fixed, consistent height.
    - Include type-relevant metrics and richer visualizations (not cards only).

11. Healthchecks
    - Healthcheck config lives in datasource settings.
    - Support rules for row-count and column-level checks.
    - Show active healthcheck count and recent status history.

12. Global settings popup
    - Add a global settings entry in top controls.
    - Popup includes default SMTP/Telegram settings (prepopulate from env if present, but editable in UI and persisted in DB).
    - Include app-level toggles such as IndexedDB debug visibility.

13. Telegram system behavior
    - Global Telegram config stores bot token and subscriber management in DB.
    - Saving token starts/updates long-running bot polling thread.
    - Bot must handle `/subscribe` and `/unsubscribe` reliably.
    - Maintain mapping of bot → subscribers and listener bindings.
    - Default listeners can be auto-populated for analysis outputs (removable).
    - Notification node can optionally detect chat for custom bot flow and send to one or many chat IDs per row.

14. Analysis version history
    - Save action always appends a new version (unlimited retention).
    - Provide rollback UI (modal selector of past versions).
    - Revert action creates a new version entry.
    - Allow renaming version titles for easier identification.

15. Preview node behavior
    - Default preview row limit is 100.
    - Preview runs immediately from current settings (no separate "apply" step).

16. IndexedDB debug popup
    - Truncate rows to fixed size.
    - Expand on click.
    - Provide copy action.

17. Documentation and standards
    - `AGENTS.md` must reflect architecture decisions and implementation standards.
    - If a fix corrects prior implementation mistakes, add the lesson to `AGENTS.md` (self-evolving rule).

---

latest findings

Telegram bot has some problems with the flow.. and even though i was able to subscribe at the end i had some conflics after unsubscribing ans subcribing back.
2026-02-14 21:01:09,278 - modules.telegram.bot - WARNING - Telegram getUpdates failed: 409 (error 4/10)
INFO: 127.0.0.1:41166 - "POST /api/v1/logs/client HTTP/1.1" 200 OK
2026-02-14 21:01:14,369 - httpx - INFO - HTTP Request: GET https://api.telegram.org/bot8129401613:AAEF86ryXiBsEHa-bY9klb5h1-Yn4ohZYwU/getUpdates?offset=456099984&timeout=30 "HTTP/1.1 409 Conflict"
2026-02-14 21:01:14,369 - modules.telegram.bot - WARNING - Telegram getUpdates failed: 409 (error 4/10)

Lineage page is still not fixed. the left pane is still on the same level as the nodes so when i move the nodes they overlap with the left pane and make it unusable.. you need to change the layout of the page so that the canvas starts after the left pane and not from the start of the screen.. or you need to make sure that left pane is always top most element and nodes cant go over it.. either way its a layout problem that needs to be fixed with different approach as your last 3 attempts did not fix it at all..

adding ai/notification node still freezes the ui.. both have the same error:
chunk-65GEI2FJ.js?v=d1e4d673:724 Uncaught TypeError: Cannot read properties of undefined (reading 'length')

    in <unknown>
    in StepConfig.svelte
    in +page.svelte
    in QueryClientProvider.svelte
    in +layout.svelte
    in root.svelte

    at NotificationConfig.svelte:42:12

im unable to drag and drop the chart to any place.. i can only add it to end.. and then only relocate.. makes no sense.. if its a visualisation node it should be able to be anywhere in the analysis and not affect the data flow.. its just for visualisation of the data at that point.. same as inline preview node.. but with different visualisation options..

Analysis flow:

Export node is still wrong:
is_hidden is basicaly just a flag that makes it hidden for other analysis.. therefore its also filterable in the datasources page
But it still should be exported as a proper iceberg table...

- you create and analysis/id
- export node is created with name export
- notification settings
- schedule setting (as schedules are bound to outputs not inputs)
- left side it has a small button that will toggle is_hidden as datasource for external analysis/id
- right side has manual build button

  when i build an analysis/id tab 2 that has as input lazyframe of an tab 1 i would expect all transformation logic from tab 1 + tab 2 would be executed an visible in the build panel with all steps.. for each run either preview or export/build

  right now the "visible" icon does god know what.. scrape it and redesign it to what it should be.. which is just a toggle to make the export datasource hidden or not for other analysis/id tabs.. it should not affect the actual export of the datasource as iceberg table and it should not affect the availability of the datasource for column stats and healthchecks and schedules and so on.. it should only affect if this datasource is visible in the datasource page for other analysis/id tabs to use as input or not.. but it should be always available for other tabs in the same analysis as input as they use the direct lazyframe and not the datasource export..

  my key is consistency and logic.. all exports write to iceberg tables. some of them are just hidden for different analysis/id's. if i toggle the is_hidden on export node it should not affect the actual export of the datasource as iceberg table and it should not affect the availability of the datasource for column stats and healthchecks and schedules and so on.. it should only affect if this datasource is visible in the datasource page for other analysis/id's.. within the same analysis it should be always available as input as they use the direct lazyframe and not the datasource export.. and therefore building an analysis/id tab that has as input lazyframe of an tab 1 should execute all transformation logic from tab 1 + tab 2 and be visible in the build panel with all steps for each run either preview or export/build

good addition:
Build comparison view — Side-by-side diff of two builds showing row count changes, schema changes, and sample data deltas. Useful for monitoring data quality over time.
