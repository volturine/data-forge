# Bugs and Issues and feature requests

## Lazyframe cross-tab build/preview execution

We need to redesign analysis execution so **lazyframe inputs are executed inside the same engine run** and not reconstructed from datasource fetches.

### Desired execution model

Example analysis tabs (single analysis ID):

```
tab1: datasource 1 -> transform logic -> export 1
tab2: lazyframe input (tab1) -> transform logic -> export 2
tab3: lazyframe input (tab2) -> transform logic -> export 3
```

Build targets must execute only the required upstream chain **within the same engine execution**, forwarding LazyFrames between tabs:

1. **Targeting export 1** should build:
   - load datasource 1
   - tab1 transform logic
   - export 1

2. **Targeting export 2** should build:
   - load datasource 1
   - tab1 transform logic
   - export 1 (but still forward the LazyFrame from tab1 downstream)
   - tab2 transform logic
   - export 2

3. **Targeting export 3** should build:
   - load datasource 1
   - tab1 transform logic
   - export 1 (LazyFrame forwarded)
   - tab2 transform logic
   - export 2 (LazyFrame forwarded)
   - tab3 transform logic
   - export 3

### Requirements

- Preceding tabs must execute in dependency order in the **same engine**.
- Lazyframe outputs are forwarded downstream; no reloading from output datasources.
- Previews & chart visualizations should reuse the same engine for the analysis and should forward LazyFrames within that engine.
- The full analysis pipeline is sent on preview/build so the engine can execute the full chain deterministically.

## Analysis experience inconsistencies + unified DAG requirement (clarification)

### Current issues

- New analysis creation is not prepopulated with an inline DataTable/view step, while new tab creation is.
- Datasource selection for new tab allows choosing an analysis tab, but the datasource node does not support it yet.
- Cross-tab work requires additional compute that should be unnecessary.
- Derived analysis tabs created before saving do not have LazyFrame schema; they only work after save.

### Required behavior

- Treat the analysis as **one big DAG** (backend + frontend): tabs are **frontend-only visualization** and grouping, not execution boundaries.
- Backend should treat analysis as a single transform file, resolving everything in one request using the full pipeline payload.
- Input datasource should be resolved immediately (LazyFrame) when the analysis is in the same DAG; no intermediate datasource reloads.
- Cross-tab previews/exports should reuse the same engine run and forward LazyFrames within that run.

## Datasource creation + branch UI regressions

- File upload must only offer file upload (no path browsing). Iceberg path is its own flow.
- Excel preflight should work reliably for uploads (run preflight without requiring a preselected sheet).
- CSV uploads must allow delimiter selection.
- Bulk upload must enforce a single file type per batch; CSV or Excel settings apply globally to the batch.
- Iceberg datasource addition should accept only the root UUID path and auto-scan branches (no branch input).
- Analysis/namespace picker should be anchored under the button (popover-style), not a centered modal.
- Branch picker buttons must be wider and handle long branch names; picker dropdown must appear above table headers.
- Build logs must include datasource create/update events for uploads, database ingest/refresh, and existing Iceberg registration.
- Output node hidden toggle must be visible again and the first row (hidden/branch/table/build) should be compact.
- Datasource UI should default to master branch and still allow selecting other branches even if latest build is different.
- Uploads should be re-ingestable from the original uploaded file; CSV/Excel settings in datasource config should trigger re-ingest into Iceberg.

### Progress notes (2026-02-20)

- Upload UI now supports upload-only flow with CSV options, Excel preflight defaults to returned sheet, and bulk uploads enforce single file type.
- Iceberg add accepts only root UUID paths (no branch), branch picker popovers are now anchored and above headers, and namespace picker is anchored under the header trigger.
- Builds filter includes datasource create/update kinds, output hidden toggle is restored with a compact row, and datasources default to master branch with master included in branch list.

---

# Data handling redesign..

whole app should be branch aware. and namespace aware
in the left top most corner we have polars/analysis
this should be analysis / namespace
and it should be changable....

UPLOAD_DIR=/home/kripso/workspace/polars-fastapi-svelte/data/uploads
CLEAN_DIR=/home/kripso/workspace/polars-fastapi-svelte/data/clean
EXPORTS_DIR=/home/kripso/workspace/polars-fastapi-svelte/data/exports

right now we have three env variables for data handling we will have one env variable for the base data dir and then we will have a structure like this:
DEFAULT_NAMESPACE=default
DATA_DIR=/home/kripso/workspace/polars-fastapi-svelte/data

then just automaticaly derive the upload and export dirs from that base dir and the namespace:
UPLOAD_DIR=${DATA_DIR}/${NAMESPACE}/uploads
CLEAN_DIR=${DATA_DIR}/${NAMESPACE}/clean

you can change NAMESPACE in the top left corner and it will automatically use the right dirs for that namespace.

In datasource creation page we will have three strategies:

## 1. Upload file

Upload file: this will upload the file to the UPLOAD_DIR and polars will read it from there and transform it to the CLEAN_DIR in iceberg format the same way we now handle exports:

- creates UUID for the datasource
- transforms it into CLEAN_DIR/${UUID}/master in iceberg format (uploads will be always master branches)
- creates a datasource record with the path to the CLEAN_DIR/${UUID}/master
- uploads should be re-ingestable (retransform to Iceberg) from the original file stored in uploads; datasource node should allow updating CSV/Excel settings used for re-ingest.

## 2. Use existing datasource (only for iceberg datasources with our structure)

- it takes the path to the datasource and checks if it is in the right structure (CLEAN_DIR/${UUID}/{branches})
- adds the datasource record with the path to the CLEAN_DIR/${UUID}/{branches}

## 3. Connect to external database

Similar to point 1. in a sence that

- we will use the original datasource as a source
- we will transform it into our structure into CLEAN_DIR
- but whenever we need to use update it we will injest it again from the original source and transform it again into our structure
  - this way we add timetravel capabilities to external datasources as well
  - but also have local iceberg copies of the data for faster use within the app
  - this means we will have to store the connection details for the external datasource in our datasource record as well so we can use it for future updates
  - but also have the path to the local iceberg copy for use within the app
- ingestion can be triggered manually by the user or automatically on a schedule (e.g. daily)
- also the target branch can be specified by the user (e.g. master or dev)

All of these will be separated then by namespace so you can have different namespaces for different projects and each namespace will have its own database for all datarelated records (datasources, analyses, exports, schedules, builds/engine runs, healthchecks) and its own data directories for uploads, clean data and exports.
That means our database has to split to two levels as well, we will have main database for all settings and such but then per namespace database for all data related records, inside the NAMESPACE_DIR/namespace.db
Schedules, builds, and healthchecks are namespace aware and their metadata is stored in the respective namespace.db.

so all our frontend and backend need to be aware of the namespaces and branches..so in analysis i can have per whole analysis output branch and that can per input datasource change the branch...

Clarifications:

- Schedules always run on the master branch.
- Lineage view is filtered by output datasource + branch. When selecting an output datasource and branch, lineage should show the upstream inputs (including their branch overrides) that contributed to that specific output branch.
- Per-namespace storage layout uses DATA_DIR/app.db for settings and DATA_DIR/namespaces/{namespace}/namespace.db for data records (datasources, analyses, schedules, builds, health checks).
