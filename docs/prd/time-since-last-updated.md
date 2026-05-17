# PRD: Time Since Last Updated

## Overview

Display "time since last updated" indicators across the platform — on datasources, analyses, and build outputs — so users can quickly assess data freshness and identify stale resources.

## Problem Statement

Data-Forge stores `created_at` and `updated_at` timestamps on most entities, but these are displayed as absolute dates (e.g., "2026-03-15 14:30") or not shown at all. Users cannot quickly answer:

- "When was this datasource last refreshed?"
- "Is this data from today or last week?"
- "Which of my analyses haven't been run recently?"

Data freshness is a critical concern for data analysis workflows. Stale data leads to incorrect decisions.

### Current State

| Entity | `updated_at` stored? | Displayed? | Relative time? |
|--------|---------------------|-----------|---------------|
| DataSource | ✅ `created_at` | ⚠️ Absolute date only | ❌ |
| Analysis | ✅ `updated_at` | ⚠️ Absolute date only | ❌ |
| EngineRun | ✅ `created_at` | ⚠️ Absolute date only | ❌ |
| Iceberg snapshots | ✅ `snapshot_timestamp_ms` | ⚠️ Absolute date only | ❌ |

## Goals

| # | Goal | Success Metric |
|---|------|----------------|
| G-1 | Relative timestamps everywhere | All list views show "2 hours ago", "3 days ago" style times |
| G-2 | Data freshness indicator | Datasources show freshness badge (fresh/stale/outdated) |
| G-3 | Sortable by freshness | Lists can be sorted by last updated |
| G-4 | Live updating | Relative times update without page refresh |
| G-5 | Configurable staleness threshold | Users define what "stale" means per datasource |

## Non-Goals

- Automated refresh when data becomes stale (see Scheduling PRD)
- Push notifications for stale data (see Notifications)
- Historical freshness tracking (only current state)

## User Stories

### US-1: See Relative Timestamps in Lists

> As a user, I want to see "5 minutes ago" instead of "2026-04-08 10:25:00" in datasource and analysis lists.

**Acceptance Criteria:**

1. All list views (datasources, analyses, builds) show relative timestamps:
   - < 1 minute: "just now"
   - < 1 hour: "12 minutes ago"
   - < 24 hours: "3 hours ago"
   - < 7 days: "2 days ago"
   - < 30 days: "2 weeks ago"
   - ≥ 30 days: "Mar 15, 2026" (absolute date)
2. Hovering over the relative time shows the absolute timestamp as a tooltip.
3. Relative times update every 60 seconds without page refresh.

### US-2: Datasource Freshness Badge

> As a user, I want to see at a glance whether a datasource's data is fresh or stale.

**Acceptance Criteria:**

1. Each datasource shows a freshness badge next to its name in list and detail views:
   - 🟢 **Fresh**: Last build/update within the freshness threshold.
   - 🟡 **Stale**: Last build/update between 1x and 2x the threshold.
   - 🔴 **Outdated**: Last build/update exceeds 2x the threshold.
   - ⚪ **Unknown**: Never built or no threshold configured.
2. Default freshness threshold: 24 hours (configurable per datasource).
3. Freshness calculated from the latest Iceberg snapshot timestamp or `updated_at`.

### US-3: Sort by Last Updated

> As a user, I want to sort datasources and analyses by when they were last updated.

**Acceptance Criteria:**

1. List views have a "Last Updated" sortable column.
2. Default sort: most recently updated first.
3. Sort persists across page navigation (stored in URL query params).

### US-4: Configure Freshness Threshold

> As a user, I want to define how long data can go without being refreshed before it's considered stale.

**Acceptance Criteria:**

1. Datasource settings include a "Freshness threshold" field.
2. Options: 1 hour, 6 hours, 12 hours, 24 hours, 7 days, 30 days, custom (minutes).
3. Setting `null` disables the freshness badge (defaults to 24h if unset).
4. Threshold stored on the DataSource model.

## Technical Design

### Frontend: Relative Time Component

Create a reusable `<RelativeTime>` Svelte component:

```svelte
<script lang="ts">
  import { untrack } from 'svelte';

  interface Props {
    timestamp: string | number;
    live?: boolean;
  }

  const { timestamp, live = true }: Props = $props();

  let now = $state(Date.now());

  $effect(() => {
    if (!live) return;
    const interval = setInterval(() => { now = Date.now(); }, 60_000);
    return () => clearInterval(interval);
  });

  const relative = $derived(formatRelative(new Date(timestamp), now));
  const absolute = $derived(new Date(timestamp).toLocaleString());
</script>

<time datetime={new Date(timestamp).toISOString()} title={absolute}>
  {relative}
</time>
```

### Frontend: Freshness Badge Component

```svelte
<script lang="ts">
  interface Props {
    lastUpdated: string;
    thresholdMs: number;
  }

  const { lastUpdated, thresholdMs }: Props = $props();

  const age = $derived(Date.now() - new Date(lastUpdated).getTime());
  const status = $derived(
    age < thresholdMs ? 'fresh' :
    age < thresholdMs * 2 ? 'stale' : 'outdated'
  );
</script>
```

### Backend Changes

**DataSource model addition:**

```python
# On DataSource or its config
freshness_threshold_minutes: int | None = None  # null = default 24h
```

**API response enrichment:**

Add `last_data_update` to datasource responses — computed from:
1. Latest Iceberg snapshot timestamp (if Iceberg-backed).
2. Latest successful build `completed_at` (if analysis-generated).
3. `updated_at` (fallback).

```python
class DataSourceResponse(BaseModel):
    # ... existing fields
    last_data_update: datetime | None
    freshness_threshold_minutes: int | None
```

**Sorting support:**

Ensure list endpoints accept `sort_by=last_data_update` and `sort_order=desc`.

### Relative Time Formatting Rules

| Age | Format | Example |
|-----|--------|---------|
| < 60s | "just now" | just now |
| < 60m | "{n} minutes ago" | 12 minutes ago |
| < 24h | "{n} hours ago" | 3 hours ago |
| < 7d | "{n} days ago" | 2 days ago |
| < 30d | "{n} weeks ago" | 2 weeks ago |
| ≥ 30d | Absolute date | Mar 15, 2026 |

Singular forms: "1 minute ago", "1 hour ago", "1 day ago".

## Acceptance Criteria

- [ ] All list views show relative timestamps with tooltip for absolute time
- [ ] Relative times update every 60 seconds without page refresh
- [ ] Datasources show freshness badges (fresh/stale/outdated)
- [ ] Freshness threshold configurable per datasource
- [ ] Default freshness threshold is 24 hours
- [ ] Lists sortable by "Last Updated"
- [ ] `last_data_update` computed from latest Iceberg snapshot or build completion
- [ ] `<RelativeTime>` component reusable across the app
- [ ] `just verify` passes
