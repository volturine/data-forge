# PRD: Lineage Revamp

## Overview

Redesign the lineage system to provide accurate, semantically meaningful dependency graphs that distinguish between dataset-level lineage (inter-analysis data flow) and code-level lineage (intra-analysis step flow), with an improved UX for exploration, filtering, and impact analysis.

## Problem Statement

The current lineage implementation (`service_lineage.py`) builds a flat graph of datasources and analyses with edges representing consumption and production relationships. However, it has several limitations:

1. **Semantic confusion**: Internal tab dependencies within an analysis are not distinguished from cross-analysis data dependencies. A tab that reads the output of a previous tab shows as a separate datasource node, conflating code-level flow with dataset-level flow.
2. **No column-level lineage**: Users cannot trace which columns in an output came from which input columns, or how transformations modified them.
3. **Limited filtering**: The `mode` parameter (`full`/`inputs`/`outputs`) is coarse — users cannot filter by depth, time range, or node type combinations.
4. **No impact analysis**: Users cannot answer "if I change this datasource, what downstream outputs will be affected?"
5. **No historical lineage**: The graph only shows current state — there is no way to see how lineage evolved over time or compare lineage between snapshots.
6. **UX limitations**: The `LineageGraph.svelte` physics-based layout works for small graphs but becomes unusable with 50+ nodes — no clustering, no search, no minimap.

### Current Architecture

```
service_lineage.py (136 lines)
├─ build_lineage(session, target_datasource_id, branch, include_internals, mode)
│  ├─ Query all DataSource records
│  ├─ Query all Analysis records
│  ├─ Query all AnalysisDataSource dependencies
│  ├─ Build node map: datasource nodes + analysis nodes
│  ├─ Classify nodes: 'source' | 'output' | 'internal'
│  └─ Build edge list: datasource→analysis (input), analysis→datasource (output)
└─ Returns: { nodes: [...], edges: [...] }
```

## Goals

| # | Goal | Success Metric |
|---|------|----------------|
| G-1 | Clear separation of dataset lineage and code lineage | Users understand that tab-internal flow is different from cross-analysis flow |
| G-2 | Column-level lineage tracking | Users can trace a column from output back to its input source(s) |
| G-3 | Impact analysis ("what breaks if I change X?") | Downstream dependency tree computed in < 2 seconds |
| G-4 | Scalable graph visualization for 100+ nodes | Clustering, search, minimap, zoom-to-fit for large graphs |
| G-5 | Historical lineage comparison | Users can compare lineage between two points in time |
| G-6 | Real-time lineage updates during builds | Lineage graph updates live when datasets are built, with build status coloring on nodes and inline progress indicators |

## Non-Goals

- Lineage for external systems (e.g., tracking data after export to S3)
- Automated lineage inference from SQL queries
- Cross-workspace lineage

## User Stories

### US-1: Dataset-Level Lineage Graph

> As a user, I want to see how datasources flow between analyses, without being confused by internal tab connections.

**Acceptance Criteria:**

1. Default lineage view shows **dataset-level** lineage: datasources as nodes, analyses as transformation nodes, edges showing data flow.
2. Internal tab dependencies (within the same analysis) are collapsed into a single analysis node.
3. Analysis nodes show: name, input count, output count, last build status.
4. Datasource nodes show: name, source type, row count, last updated.
5. Edge labels show: branch name (if non-default).
6. Toggle to expand an analysis node and see its internal tab flow (code-level lineage).

### US-2: Column-Level Lineage

> As a user, I want to click on a column in an output datasource and see which input columns it was derived from and what transformations were applied.

**Acceptance Criteria:**

1. Click on a datasource node → shows column list.
2. Click on a column → highlights the lineage path (upstream columns that contributed to it).
3. Transformation annotations on edges: "renamed from X", "aggregated from Y", "computed expression".
4. Column lineage traced through: select, rename, with_columns, group_by, join operations.
5. For complex expressions (e.g., `col_a + col_b`), show all contributing columns.

### US-3: Impact Analysis

> As a user, I want to see what will be affected if I modify or rollback a datasource.

**Acceptance Criteria:**

1. Right-click a datasource node → "Show Impact" action.
2. Impact view highlights: all downstream analyses and datasources that transitively depend on this datasource.
3. Impact summary: count of affected analyses, affected datasources, affected schedules.
4. Severity indicators: direct dependency (1 hop) vs. transitive dependency (2+ hops).
5. Exportable as list (for communication/review).

### US-4: Lineage Search and Filtering

> As a user, I want to search for specific datasources or analyses in the lineage graph and filter by various criteria.

**Acceptance Criteria:**

1. Search bar in lineage view: search by datasource/analysis name.
2. Search result highlights matching nodes and centers the view.
3. Filter panel:
   - Node type: datasources only, analyses only, or both.
   - Source type: file, database, iceberg, kaggle, etc.
   - Status: active, stale, errored.
   - Depth: limit hops from a selected node (1, 2, 3, all).
   - Time range: show only nodes modified within a time window.
4. Active filters shown as chips with clear-all action.

### US-5: Scalable Graph Visualization

> As a user, I want the lineage graph to remain usable even with 100+ nodes.

**Acceptance Criteria:**

1. Auto-clustering: groups of related nodes (e.g., all outputs of one analysis) collapse into clusters.
2. Minimap in corner showing full graph with viewport indicator.
3. Zoom-to-fit button centers and scales the graph to show all nodes.
4. Node detail panel (click-to-inspect) instead of cramming info on the node itself.
5. Keyboard navigation: arrow keys to move between connected nodes, Enter to select.
6. Performance: render 200 nodes at 60fps (virtualized rendering for off-screen nodes).

### US-6: Historical Lineage Comparison

> As a user, I want to compare the lineage graph between two points in time to see what changed.

**Acceptance Criteria:**

1. Time slider or date picker to select a historical point.
2. Diff view: added nodes (green), removed nodes (red), modified edges (yellow).
3. Summary of changes: "3 datasources added, 1 analysis removed, 5 edges changed".
4. Side-by-side or overlay comparison modes.

### US-7: Live Build Status on Lineage Nodes

> As a user, I want lineage nodes to visually reflect when a dataset is currently being built, so I can see build activity across the graph.

**Acceptance Criteria:**

1. Lineage graph updates in real time when a build starts, progresses, or completes.
2. Datasource nodes show build status via color coding: idle (default), building (animated/pulsing accent), succeeded (green flash then default), failed (red).
3. Analysis nodes that are currently executing show a building indicator.
4. Clicking a node that is currently building shows an expanded inline progress view: current step, progress percentage, elapsed time.
5. Build status coloring is available as a toggle option in the lineage toolbar (can be enabled/disabled).
6. When a build completes, the node updates its metadata (row count, last updated) without requiring a page refresh.
7. Multiple simultaneous builds across different analyses are all reflected in the graph concurrently.

## Technical Design

### Backend

#### Refactored Lineage Service

```
modules/lineage/                  # NEW: standalone lineage module
├── __init__.py
├── routes.py                     # Lineage API endpoints
├── service.py                    # Lineage graph construction
├── column_lineage.py             # Column-level lineage tracing
├── impact.py                     # Impact analysis
├── schemas.py                    # Pydantic models
└── models.py                     # LineageSnapshot model (optional)
```

#### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/lineage` | Get lineage graph (dataset-level) |
| `GET` | `/api/v1/lineage/analysis/{id}` | Get code-level lineage for an analysis |
| `GET` | `/api/v1/lineage/column/{datasource_id}/{column_name}` | Trace column lineage |
| `GET` | `/api/v1/lineage/impact/{datasource_id}` | Get downstream impact tree |
| `GET` | `/api/v1/lineage/search` | Search nodes by name |
| `GET` | `/api/v1/lineage/history` | Get lineage at a historical point |
| `GET` | `/api/v1/lineage/diff` | Compare lineage between two timestamps |

#### Lineage Graph Model

```python
class LineageNode(BaseModel):
    id: str
    type: Literal["datasource", "analysis"]
    name: str
    metadata: dict  # type-specific metadata

class DatasourceLineageNode(LineageNode):
    type: Literal["datasource"] = "datasource"
    source_type: str  # file, iceberg, kaggle, etc.
    node_kind: Literal["source", "output", "internal"]
    row_count: int | None
    column_count: int | None
    last_updated: datetime | None
    branch: str | None

class AnalysisLineageNode(LineageNode):
    type: Literal["analysis"] = "analysis"
    tab_count: int
    step_count: int
    last_build_status: str | None  # success, failed, never_run
    last_build_time: datetime | None

class LineageEdge(BaseModel):
    source: str  # node ID
    target: str  # node ID
    edge_type: Literal["input", "output", "tab_dependency"]
    branch: str | None
    columns: list[str] | None  # columns flowing through this edge

class LineageGraph(BaseModel):
    nodes: list[LineageNode]
    edges: list[LineageEdge]
    clusters: list[NodeCluster] | None  # for auto-grouping

class NodeCluster(BaseModel):
    id: str
    name: str
    node_ids: list[str]
    collapsed: bool = True
```

#### Column Lineage Tracing

```python
async def trace_column_lineage(
    session: AsyncSession,
    datasource_id: str,
    column_name: str,
) -> ColumnLineage:
    """Trace a column back to its source(s) through transformations."""
    # 1. Find the analysis that produces this datasource
    analysis = await get_producing_analysis(session, datasource_id)
    if not analysis:
        return ColumnLineage(column=column_name, sources=[ColumnSource(
            datasource_id=datasource_id, column=column_name, transform="origin"
        )])

    # 2. Walk the pipeline steps backward
    pipeline = analysis.pipeline_definition
    sources = []
    for tab in reversed(pipeline["tabs"]):
        for step in reversed(tab["steps"]):
            # Check if this step produces the target column
            # Trace through: select, rename, with_columns, group_by, join
            column_name = trace_through_step(step, column_name)
            if column_name is None:
                break

    # 3. Recurse into input datasource if it's also an analysis output
    ...

    return ColumnLineage(column=original_column, path=transformation_path, sources=sources)
```

#### Impact Analysis

```python
async def compute_impact(
    session: AsyncSession,
    datasource_id: str,
    max_depth: int = 10,
) -> ImpactTree:
    """Compute transitive downstream dependencies."""
    visited = set()
    queue = [(datasource_id, 0)]
    impact_nodes = []

    while queue:
        current_id, depth = queue.pop(0)
        if current_id in visited or depth > max_depth:
            continue
        visited.add(current_id)

        # Find analyses that consume this datasource
        consumers = await get_consumer_analyses(session, current_id)
        for analysis in consumers:
            # Find datasources produced by this analysis
            outputs = await get_analysis_outputs(session, analysis.id)
            for output in outputs:
                impact_nodes.append(ImpactNode(
                    datasource_id=output.id,
                    analysis_id=analysis.id,
                    depth=depth + 1,
                ))
                queue.append((output.id, depth + 1))

    return ImpactTree(
        root_datasource_id=datasource_id,
        affected_nodes=impact_nodes,
        total_affected_datasources=len({n.datasource_id for n in impact_nodes}),
        total_affected_analyses=len({n.analysis_id for n in impact_nodes}),
    )
```

### Frontend

#### Refactored LineageGraph

Replace `LineageGraph.svelte` with a more capable implementation:

```
components/lineage/
├── LineageCanvas.svelte          # Main graph canvas (replaces LineageGraph.svelte)
├── LineageNode.svelte            # Individual node component
├── LineageEdge.svelte            # Edge rendering with labels
├── LineageMinimap.svelte         # Minimap overview
├── LineageSearch.svelte          # Search and filter panel
├── LineageFilters.svelte         # Filter chips and controls
├── LineageImpactPanel.svelte     # Impact analysis side panel
├── LineageColumnTrace.svelte     # Column lineage overlay
├── LineageTimeline.svelte        # Historical comparison slider
└── LineageDiff.svelte            # Diff overlay for comparison
```

#### Graph Rendering Strategy

- Use HTML/CSS-based rendering (current approach) with virtualization for off-screen nodes.
- Elk.js (Eclipse Layout Kernel) for automatic hierarchical layout — better than physics-based for DAGs.
- Cluster support: nodes grouped by analysis, collapsible.
- SVG edges with curved paths and directional arrows.

#### Interaction Model

```
Default view (dataset-level):
  [Source DS] ──→ [Analysis A] ──→ [Output DS] ──→ [Analysis B] ──→ [Output DS2]

Expanded analysis (click to expand):
  [Source DS] ──→ ┌──────────────────────────┐ ──→ [Output DS]
                  │ Analysis A               │
                  │  Tab 1: filter → select  │
                  │  Tab 2: join → aggregate │
                  └──────────────────────────┘

Column trace (click column in Output DS):
  [Source DS].revenue ──(select)──→ [Analysis A] ──(group_by sum)──→ [Output DS].total_revenue
```

### Dependencies

| Package | Version | Ecosystem | Purpose |
|---------|---------|-----------|---------|
| `elkjs` | `>=0.9.0` | npm | Hierarchical graph layout engine (optional, for improved layout) |

### Security Considerations

- Lineage graph is read-only — no mutations.
- Column lineage traces pipeline definitions, not actual data — no data leakage risk.
- Impact analysis returns metadata only (IDs, names, counts) — no row-level data.

## Migration

- Migrate existing `/api/v1/datasource/lineage` to new `/api/v1/lineage` endpoint.
- Keep old endpoint as deprecated redirect for backward compatibility.
- Optional: Alembic migration for `lineage_snapshots` table if implementing historical lineage.

## Rollout Plan

| Phase | Scope | Duration |
|-------|-------|----------|
| 1 | Backend: Refactored lineage service with dataset/code separation | 3 days |
| 2 | Backend: Column lineage tracing | 3 days |
| 3 | Backend: Impact analysis | 2 days |
| 4 | Backend: Search, filtering, historical endpoints | 2 days |
| 5 | Frontend: LineageCanvas with clustering and minimap | 4 days |
| 6 | Frontend: Search, filters, impact panel | 3 days |
| 7 | Frontend: Column trace overlay | 2 days |
| 8 | Frontend: Historical comparison | 2 days |
| 9 | Testing: Large graphs, performance, edge cases | 3 days |

## Open Questions

1. Should column lineage be computed on-demand (trace at query time) or pre-computed (stored after each build)?
2. Should lineage snapshots be stored in the DB or computed from pipeline version history?
3. How do we handle lineage for UDFs (user-defined functions) that may have opaque column transformations?
4. Should we integrate with external lineage tools (e.g., OpenLineage, Marquez)?
