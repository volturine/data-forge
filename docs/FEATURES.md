# Data-Forge Features

> ✅ = Implemented | ⬜ = Planned

---

## Analyses

- ✅ Browse, search, and sort all analyses from the gallery view
- ✅ Create new analyses and open them in the visual editor
- ✅ Delete individual analyses or bulk-delete a selection
- ⬜ Duplicate an existing analysis to reuse its pipeline structure
- ⬜ Duplicate a single tab within an analysis
- ⬜ New analysis creation flow with templates and AI-assisted generation
- ⬜ Import/export pipeline definitions as JSON

## Pipeline Editor

- ✅ Multi-tab canvas — organize transformations across multiple named tabs
- ✅ Drag-and-drop step ordering directly on the canvas
- ✅ Version history — restore or rename any previously saved version of an analysis
- ✅ Instant data preview at any step without running the full pipeline
- ✅ Unified DAG execution — tabs resolve as one pipeline; no intermediate reloads
- ⬜ Horizontal node config revamp — optimized layouts for vertical and horizontal panel positions

## Pipeline Steps

- ✅ **Filter** — keep rows matching a condition
- ✅ **Select** — choose which columns to keep
- ✅ **Sort** — order rows by one or more columns
- ✅ **Group By** — aggregate rows into groups with sum, mean, count, etc.
- ✅ **Join** — combine two datasets on matching keys
- ✅ **Pivot / Unpivot** — reshape data between wide and long formats
- ✅ **Rename** — rename one or more columns
- ✅ **Drop** — remove unwanted columns
- ✅ **Fill Null** — replace missing values with a constant or strategy
- ✅ **Expression** — write custom Polars expressions for arbitrary transformations
- ✅ **With Columns** — add or overwrite columns using expressions
- ✅ **String Methods** — apply string operations (trim, split, replace, etc.)
- ✅ **Time Series** — resample, rolling windows, and date truncation
- ✅ **Explode** — expand list columns into separate rows
- ✅ **Deduplicate** — remove duplicate rows
- ✅ **Top K** — keep the N highest or lowest rows by a column
- ✅ **Limit / Sample** — take a fixed count or random sample of rows
- ✅ **Union By Name** — stack two datasets vertically by matching column names
- ✅ **View** — inline data table preview (pass-through; does not affect downstream data)
- ✅ **Plot** — inline chart visualization (bar, line, scatter, etc.)
- ✅ **Export** — write tab output to an Iceberg dataset
- ✅ **Download** — produce a one-off CSV, Parquet, or JSON file
- ✅ **Notification** — send an alert after a step completes
- ✅ **AI** — use an AI model to generate or assist with transformation logic

## Datasources

- ✅ Upload files: CSV (with delimiter selection) and Excel (with sheet detection)
- ✅ Bulk upload multiple files of the same type in one batch
- ✅ Connect to external databases and ingest data into local Iceberg copies
- ✅ Register existing Iceberg datasets by UUID path with automatic branch scanning
- ✅ Preview data and schema for any datasource
- ✅ Download datasource contents as CSV, Parquet, or JSON
- ✅ Time-travel snapshot selection for Iceberg datasets
- ✅ Configure per-datasource health checks
- ✅ Hide datasources from external discovery without removing them
- ✅ Provenance indicator — shows whether a datasource was uploaded or built by an analysis
- ✅ Direct link from an analysis-built datasource back to its owning analysis
- ⬜ Kaggle connection — browse, search, and ingest Kaggle datasets directly
- ⬜ Hugging Face datasets — browse, search, and ingest HF datasets directly
- ⬜ Monitored import folder — auto-ingest files or partitioned Parquet folders added to a watched directory

## Scheduling

- ✅ Create schedules targeting output datasets (not analyses directly)
- ✅ Three trigger types: cron (time-based), depends-on (DAG ordering), and event (upstream dataset update)
- ✅ Schedules always resolve to the latest analysis version at execution time
- ✅ Schedule controls accessible from the output node, datasource config, lineage panel, and schedules page

## Monitoring

- ✅ **Builds** — full history of build and preview runs with status, timings, and error details
- ✅ **Schedules** — view and manage all active schedules in one place
- ✅ **Health Checks** — track datasource health check results over time
- ✅ Filter and search across builds, schedules, and health checks
- ✅ Expand individual runs to inspect the request payload, result, query plan, and per-step timings
- ✅ Compare two runs side-by-side for row, schema, and timing differences
- ✅ Build length tracking and time since last updated
- ⬜ Live build preview — progress bar, current step indicator, per-step timings, ETA
- ⬜ Query plan visualization during build execution
- ⬜ Resource monitoring (CPU, memory, threads) during builds
- ⬜ Cancel build in progress

## Lineage

- ✅ Visual graph of all datasets and analyses and how they connect
- ✅ Dependency edges show which analyses consume which datasources
- ✅ Open a datasource panel directly from the lineage view to inspect or schedule it
- ⬜ Lineage revamp — column-level lineage, impact analysis, clustering for large graphs, live build status on nodes

## Snapshot & Time-Travel

- ✅ Iceberg snapshot selection for datasource inputs
- ⬜ Snapshot rollback — restore a datasource to a previous snapshot with audit trail

## UDFs (User-Defined Functions)

- ✅ Create and manage reusable custom functions
- ✅ UDFs are available as expressions inside any pipeline step

## Notifications

- ✅ SMTP email notifications for build results and step-level alerts
- ✅ Telegram bot integration for real-time notifications
- ✅ Per-output and per-step notification configuration

## AI Integration

- ✅ Connect to Ollama (local/self-hosted and remote)
- ✅ Connect to OpenAI (local/self-hosted and remote)
- ✅ Connect to OpenRouter (remote)
- ✅ Connect to Hugging Face Inference API (remote)
- ✅ Use AI inside the pipeline to assist with expressions and per-row LLM transformations
- ✅ Test provider connectivity and browse available models from within the app
- ⬜ Hugging Face model hub — pull models to local storage and load onto GPU
- ⬜ In-app AI chat for conversational analysis assistance

## Namespaces & Branches

- ✅ Multiple namespaces with fully isolated databases and data directories
- ✅ Switch namespaces from the top-left corner; all operations follow the selected namespace
- ✅ Branch-aware datasources — select a specific branch (e.g., master, dev) per input in a pipeline
- ✅ Lineage filtered by output datasource and branch

## Data & Storage

- ✅ All data stored locally — no cloud, no subscriptions, nothing leaves your machine
- ✅ Apache Iceberg format for all managed outputs with snapshot and time-travel support
- ✅ Powered by Polars for fast, memory-efficient computation
- ✅ Isolated compute subprocess per analysis for safe parallel execution
- ⬜ S3 storage support — use an S3 path as `DATA_DIR` for cloud-based storage
- ✅ PostgreSQL backend — supported metadata storage runtime

## Dashboards

- ⬜ Analytical dashboards — configurable, shareable runtime views with variables, charts, and KPIs

## MCP Tool Integration

- ✅ Core API routes exposed as MCP tools for AI assistant access
- ✅ Enables AI agents to list datasources, run analyses, inspect builds, and more

## User Interface

- ⬜ Mobile-first UI redesign — responsive layouts optimized for touch and small screens
- ⬜ Settings page under profile — consolidated configuration in the user profile area
- ⬜ SQL and Polars snippet export — copy generated code for external use

## Deployment & Operations

- ✅ Docker deployment — fixed-role production runtime with published `api`, `scheduler`, and `worker` images
- ✅ Environment variable configuration — full reference of all configurable options
- ⬜ Serve under a custom subdomain rather than `localhost:8000`
- ⬜ All-in-one release script for streamlined builds and deploys
- ⬜ Documentation updates — README, contribution guidelines, environment variables

## Code & Repository

- ⬜ Clean up git history
- ⬜ Contribution declaration and guidelines
