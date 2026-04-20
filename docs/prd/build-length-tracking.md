# PRD: Build Length Tracking

## Overview

Track and display build execution duration at the overall build level and per-step level, enabling users to identify slow steps, compare build performance over time, and set duration-based alerts.

## Problem Statement

Data-Forge already records `duration_ms` and `step_timings` on the `EngineRun` model, but this data is not surfaced prominently in the UI. Users cannot:

- See at a glance how long their builds take.
- Identify which pipeline steps are bottlenecks.
- Track whether build times are trending up or down over time.
- Set alerts for builds that exceed expected duration.

### Current State

| Capability | Status |
|-----------|--------|
| `EngineRun.duration_ms` | ✅ Recorded |
| `EngineRun.step_timings` | ✅ Dict of step_id → duration_ms |
| `EngineRun.progress` | ✅ 0.0–1.0 during execution |
| Build history list | ✅ Shows status, timestamp |
| Duration in build list | ❌ Not displayed |
| Per-step timing breakdown | ❌ Not displayed |
| Duration trend chart | ❌ Not available |
| Duration alerts | ❌ Not available |

## Goals

| # | Goal | Success Metric |
|---|------|----------------|
| G-1 | Display build duration in the build history list | Duration shown for every completed/errored build |
| G-2 | Per-step timing breakdown | Users can see which step took the longest in any build |
| G-3 | Duration trend visualization | Chart showing build duration over the last N builds |
| G-4 | Live elapsed time | Running builds show a live timer |
| G-5 | Duration-based warnings | Optional threshold that flags builds exceeding expected duration |

## Non-Goals

- Profiling within a single Polars operation (e.g., which Polars physical plan node is slow)
- Distributed tracing (single-machine only)
- Cost estimation based on duration
- Automatic performance optimization suggestions

## User Stories

### US-1: See Build Duration in History

> As a user, I want to see how long each build took in the build history list.

**Acceptance Criteria:**

1. Build history list shows a "Duration" column.
2. Duration formatted as human-readable: `1.2s`, `45s`, `2m 15s`, `1h 3m`.
3. Running builds show elapsed time with a live-updating counter.
4. Failed builds show duration up to the point of failure.

### US-2: View Per-Step Timing Breakdown

> As a user, I want to see how long each step took within a build.

**Acceptance Criteria:**

1. Clicking on a build in the history opens a detail view.
2. Detail view shows a waterfall/bar chart of step timings.
3. Steps ordered by execution sequence.
4. Each bar shows: step name, duration, percentage of total build time.
5. The slowest step is visually highlighted.

### US-3: Track Build Duration Trends

> As a user, I want to see if my builds are getting slower over time.

**Acceptance Criteria:**

1. Build detail or datasource overview includes a duration trend chart.
2. Chart shows duration (y-axis) vs. build number or date (x-axis) for the last 20 builds.
3. Trend line (moving average) indicates direction.
4. Chart distinguishes successful vs. failed builds (different colors).

### US-4: Live Build Timer

> As a user, I want to see how long the current build has been running.

**Acceptance Criteria:**

1. When a build is in progress, the build panel shows a live elapsed timer.
2. Timer starts from build initiation and updates every second.
3. Timer persists if the user navigates away and returns.
4. Timer freezes when the build completes and shows final duration.

### US-5: Duration Threshold Warnings

> As a user, I want to be notified if a build takes unusually long.

**Acceptance Criteria:**

1. Optional `build_timeout_warning_ms` field on Analysis or datasource output config.
2. If a build exceeds this threshold, the UI shows a warning indicator.
3. Existing notification channels (Telegram, email) can include duration warnings.
4. Default: no threshold (opt-in).

## Technical Design

### Backend Changes

**API response enrichment:**

The `EngineRun` response already includes `duration_ms` and `step_timings`. Ensure:
- `duration_ms` is always populated for completed/errored runs.
- `step_timings` includes step names (not just IDs) — join with pipeline definition.
- Add a computed field `duration_formatted` for convenience (or format on frontend).

**New endpoint for duration stats:**

```
GET /api/v1/engine-runs/stats?analysis_id={id}&kind=BUILD&limit=20
Response: {
  runs: [{ id, started_at, duration_ms, status }],
  avg_duration_ms: number,
  p50_duration_ms: number,
  p95_duration_ms: number,
  trend: "improving" | "stable" | "degrading"
}
```

**Duration threshold:**

Add optional `build_timeout_warning_ms` to Analysis or output config. The compute service checks this after build completion and flags the engine run.

### Frontend Changes

**Build history list:**
- Add "Duration" column with formatted value.
- Running builds: show live timer component using `setInterval` + elapsed since `started_at`.

**Build detail panel:**
- Horizontal bar chart for step timings (use existing charting library or simple CSS bars).
- Slowest step highlighted with accent color.
- Tooltip showing exact milliseconds.

**Duration trend chart:**
- Line chart with last 20 builds.
- Can use a lightweight chart library or SVG-based component.
- Show average line as dashed overlay.

### Data Model

No schema changes needed — `duration_ms` and `step_timings` already exist on `EngineRun`. Only the duration threshold is new:

```python
# On Analysis model or output config
build_timeout_warning_ms: int | None = None
```

## Acceptance Criteria

- [ ] Build history list shows formatted duration for all completed/errored builds
- [ ] Running builds show a live-updating elapsed timer
- [ ] Build detail view shows per-step timing breakdown as a bar chart
- [ ] Slowest step is visually highlighted
- [ ] Duration trend chart shows last 20 builds with trend indicator
- [ ] Optional duration threshold triggers a warning indicator
- [ ] Duration stats endpoint returns avg, p50, p95 metrics
- [ ] `just verify` passes
