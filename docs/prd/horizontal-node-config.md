# PRD: Horizontal Node Config Revamp

## Overview

Redesign the step configuration panel so that it has two isolated layout implementations — vertical and horizontal — each optimized for its available space. The current implementation uses a single vertical column layout regardless of where the panel is docked (right or bottom). When the panel is docked at the bottom (horizontal space available, limited vertical space), the config should use a horizontal-optimized layout that makes effective use of wide, short space. Both layouts must be implemented as isolated plugin files.

## Problem Statement

The analysis editor supports two config panel positions: **right** (default, narrow tall panel) and **bottom** (wide short panel). The panel position is toggleable and persisted. However, the config content inside the panel is always the same vertical column layout (`flexDirection: 'column'`). When the panel is docked at the bottom, users get a vertically scrolling column in a wide short space — this wastes horizontal screen real estate and forces excessive scrolling for operations with many fields (e.g., FilterConfig with multiple conditions, PlotConfig with data + styling tabs).

### Current State

```
Right panel (350px wide, full height):     Bottom panel (full width, 300px tall):
┌──────────────┐                           ┌──────────────────────────────────┐
│ Filter Config│                           │ Filter Config                    │
│              │                           │                                  │
│ Column: ▾   │                           │ Column: ▾                        │
│ Operator: ▾ │                           │ Operator: ▾                      │
│ Value: ___  │                           │ Value: ___                       │
│             │                           │ + Add condition                   │
│ + Add cond  │                           │                                  │
│             │                           │ (scrolls vertically — same       │
│ (works well │                           │  layout, wastes horizontal space)│
│  in narrow  │                           │                                  │
│  tall space)│                           └──────────────────────────────────┘
└──────────────┘                           ↑ NOT optimized for this orientation
```

### Target State

```
Right panel (vertical layout plugin):      Bottom panel (horizontal layout plugin):
┌──────────────┐                           ┌──────────────────────────────────────────┐
│ Filter Config│                           │ Filter Config                            │
│              │                           │ ┌────────────┬────────────┬────────────┐ │
│ Column: ▾   │                           │ │ Column: ▾  │ Operator:▾ │ Value: ___ │ │
│ Operator: ▾ │                           │ ├────────────┼────────────┼────────────┤ │
│ Value: ___  │                           │ │ Column: ▾  │ Operator:▾ │ Value: ___ │ │
│             │                           │ └────────────┴────────────┴────────────┘ │
│ + Add cond  │                           │ [+ Add condition]                        │
│             │                           └──────────────────────────────────────────┘
│ (unchanged) │                            ↑ Optimized: fields flow horizontally
└──────────────┘
```

## Goals

| # | Goal | Success Metric |
|---|------|----------------|
| G-1 | Horizontal layout optimized for wide, short panel | No vertical scrolling needed for configs with ≤ 5 fields |
| G-2 | Isolated plugin architecture | Vertical and horizontal layouts in separate files, zero coupling |
| G-3 | All 30+ operation configs supported in both layouts | Every operation renders correctly in both orientations |
| G-4 | Automatic layout switching | Layout changes automatically when config position toggles |
| G-5 | No regression in vertical layout | Existing vertical config behavior unchanged |

## Non-Goals

- New operation types (only layout changes for existing operations)
- Mobile-specific config layout (covered by Mobile-First UI PRD)
- Drag-to-resize within the config panel content area
- Responsive breakpoints within the config panel (always vertical OR horizontal, not both)

## User Stories

### US-1: Horizontal Config Layout for Bottom Panel

> As a user, when I dock the config panel at the bottom, I want the step configuration to use horizontal space efficiently.

**Acceptance Criteria:**

1. When `configPosition === 'bottom'`, config uses horizontal layout plugin.
2. Form fields arranged in rows (side by side) instead of stacked vertically.
3. Condition rows (filter, sort) show all fields in a single horizontal row.
4. Multi-field sections use grid layout to fill horizontal space.
5. No horizontal overflow — fields wrap responsively within the panel width.

### US-2: Automatic Layout Switching

> As a user, when I toggle the config panel position, the layout switches smoothly.

**Acceptance Criteria:**

1. Toggle button switches position AND layout simultaneously.
2. No flash of unstyled content during switch.
3. User's config state (field values, scroll position) preserved during switch.
4. Transition is instant (no animation delay).

### US-3: Plugin Architecture

> As a developer, I want vertical and horizontal layouts in separate files so they can evolve independently.

**Acceptance Criteria:**

1. Each operation has two config components: `FilterConfigVertical.svelte` and `FilterConfigHorizontal.svelte` (or equivalent pattern).
2. A resolver function maps `(operationType, orientation)` → component.
3. Adding a new operation requires creating two files (one per orientation).
4. Shared logic (validation, state management) extracted to a common module.
5. Each plugin file is self-contained — no imports between vertical and horizontal files.

## Technical Design

### Architecture

#### Plugin Pattern

```
components/operations/
├── shared/                              # Shared logic (non-visual)
│   ├── filter-logic.ts                  # Filter validation, state, types
│   ├── sort-logic.ts
│   ├── groupby-logic.ts
│   └── ...
├── vertical/                            # Vertical layout plugins
│   ├── FilterConfigVertical.svelte
│   ├── SortConfigVertical.svelte
│   ├── GroupByConfigVertical.svelte
│   ├── PlotConfigVertical.svelte
│   ├── JoinConfigVertical.svelte
│   ├── WithColumnsConfigVertical.svelte
│   ├── SelectConfigVertical.svelte
│   └── ... (all 30+ operations)
├── horizontal/                          # Horizontal layout plugins
│   ├── FilterConfigHorizontal.svelte
│   ├── SortConfigHorizontal.svelte
│   ├── GroupByConfigHorizontal.svelte
│   ├── PlotConfigHorizontal.svelte
│   ├── JoinConfigHorizontal.svelte
│   ├── WithColumnsConfigHorizontal.svelte
│   ├── SelectConfigHorizontal.svelte
│   └── ... (all 30+ operations)
└── registry.ts                          # Plugin resolver
```

#### Plugin Resolver

```typescript
// components/operations/registry.ts

import type { Component } from 'svelte';

type Orientation = 'vertical' | 'horizontal';

const registry: Record<string, Record<Orientation, () => Promise<{ default: Component }>>> = {
    filter: {
        vertical: () => import('./vertical/FilterConfigVertical.svelte'),
        horizontal: () => import('./horizontal/FilterConfigHorizontal.svelte'),
    },
    sort: {
        vertical: () => import('./vertical/SortConfigVertical.svelte'),
        horizontal: () => import('./horizontal/SortConfigHorizontal.svelte'),
    },
    // ... all operations
};

export function getConfigComponent(
    operationType: string,
    orientation: Orientation,
): () => Promise<{ default: Component }> {
    const entry = registry[operationType];
    if (!entry) throw new Error(`Unknown operation: ${operationType}`);
    return entry[orientation] ?? entry['vertical']; // fallback to vertical
}
```

#### StepConfig Integration

```svelte
<!-- StepConfig.svelte (modified) -->
<script lang="ts">
    import { getConfigComponent } from '../operations/registry';

    let { step, orientation = 'vertical' } = $props<{
        step: PipelineStep;
        orientation: 'vertical' | 'horizontal';
    }>();

    const ConfigComponent = $derived.by(() => {
        return getConfigComponent(step.type, orientation);
    });
</script>

{#await ConfigComponent() then module}
    <svelte:component this={module.default} {step} />
{/await}
```

#### Page Integration

```svelte
<!-- routes/analysis/[id]/+page.svelte (modified) -->
<script lang="ts">
    let configOrientation = $derived(
        configPosition === 'bottom' ? 'horizontal' : 'vertical'
    );
</script>

<StepConfig step={selectedStep} orientation={configOrientation} />
```

### Horizontal Layout Patterns

Each horizontal config plugin follows these patterns:

#### Pattern 1: Inline Fields (for simple operations)

```svelte
<!-- SortConfigHorizontal.svelte -->
<div class={css({ display: 'flex', gap: '3', alignItems: 'center', flexWrap: 'wrap' })}>
    <div class={css({ flex: '1', minWidth: '150px' })}>
        <label>Column</label>
        <ColumnPicker bind:value={config.column} />
    </div>
    <div class={css({ flex: '0 0 auto' })}>
        <label>Direction</label>
        <SegmentToggle options={['asc', 'desc']} bind:value={config.direction} />
    </div>
    <div class={css({ flex: '0 0 auto' })}>
        <label>Nulls</label>
        <SegmentToggle options={['first', 'last']} bind:value={config.nulls_last} />
    </div>
</div>
```

#### Pattern 2: Table Rows (for list-based operations like filter conditions)

```svelte
<!-- FilterConfigHorizontal.svelte -->
<table class={css({ width: '100%', borderCollapse: 'collapse' })}>
    <thead>
        <tr>
            <th>Column</th>
            <th>Operator</th>
            <th>Value</th>
            <th>Logic</th>
            <th></th>
        </tr>
    </thead>
    <tbody>
        {#each conditions as condition, i}
            <tr>
                <td><ColumnPicker bind:value={condition.column} /></td>
                <td><OperatorPicker bind:value={condition.operator} /></td>
                <td><ValueInput bind:value={condition.value} /></td>
                <td><SegmentToggle options={['AND', 'OR']} bind:value={condition.logic} /></td>
                <td><button onclick={() => removeCondition(i)}>✕</button></td>
            </tr>
        {/each}
    </tbody>
</table>
```

#### Pattern 3: Side-by-Side Panels (for complex operations like plot)

```svelte
<!-- PlotConfigHorizontal.svelte -->
<div class={css({ display: 'flex', gap: '4', height: '100%' })}>
    <div class={css({ flex: '1', overflowY: 'auto' })}>
        <!-- Data config: chart type, x, y, color -->
        <div class={css({ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2' })}>
            <Field label="Chart Type"><ChartTypePicker bind:value={config.chart_type} /></Field>
            <Field label="X Axis"><ColumnPicker bind:value={config.x} /></Field>
            <Field label="Y Axis"><ColumnPicker bind:value={config.y} /></Field>
            <Field label="Color"><ColumnPicker bind:value={config.color} /></Field>
        </div>
    </div>
    <div class={css({ width: '1px', backgroundColor: 'border.primary' })} />
    <div class={css({ flex: '1', overflowY: 'auto' })}>
        <!-- Styling config: title, legend, colors -->
        <div class={css({ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2' })}>
            <Field label="Title"><TextInput bind:value={config.title} /></Field>
            <Field label="Legend"><Toggle bind:value={config.show_legend} /></Field>
        </div>
    </div>
</div>
```

### Shared Logic Extraction

Extract non-visual logic from existing config components into shared modules:

```typescript
// components/operations/shared/filter-logic.ts

export interface FilterCondition {
    column: string;
    operator: FilterOperator;
    value: string | number | boolean | null;
    logic: 'AND' | 'OR';
}

export type FilterOperator = '=' | '!=' | '>' | '<' | '>=' | '<=' | 'contains' | 'starts_with' | 'in' | 'is_null' | 'is_not_null';

export function validateCondition(condition: FilterCondition, columns: ColumnInfo[]): string | null {
    if (!condition.column) return 'Column is required';
    if (!condition.operator) return 'Operator is required';
    // ... validation logic
    return null;
}

export function createEmptyCondition(): FilterCondition {
    return { column: '', operator: '=', value: '', logic: 'AND' };
}
```

### Migration Strategy

Since there are 30+ operation config components, migration should be incremental:

1. **Phase 1**: Create the plugin architecture (registry, resolver, StepConfig integration).
2. **Phase 2**: Migrate existing config components to `vertical/` directory (rename, no logic changes).
3. **Phase 3**: Create horizontal variants for the top 5 most-used operations (filter, sort, select, group_by, with_columns).
4. **Phase 4**: Create horizontal variants for remaining operations.
5. **Fallback**: Operations without a horizontal variant use the vertical layout in both positions (graceful degradation).

### Dependencies

No new dependencies required.

### Security Considerations

- No security implications — this is a pure frontend layout change.
- Config values are validated by the same shared logic regardless of orientation.
- Lazy-loaded component imports use dynamic `import()` which is tree-shaken by Vite.

## Migration

- No database migration.
- No API changes.
- Frontend refactoring only.
- Existing operation config components moved to `vertical/` subdirectory.
- Shared logic extracted from existing components (no behavior changes).

## Rollout Plan

| Phase | Scope | Duration |
|-------|-------|----------|
| 1 | Plugin architecture: registry, resolver, StepConfig integration | 2 days |
| 2 | Extract shared logic from top 5 operations | 2 days |
| 3 | Move existing configs to `vertical/` directory | 1 day |
| 4 | Create horizontal variants for filter, sort, select, group_by, with_columns | 4 days |
| 5 | Create horizontal variants for join, plot, pivot, unpivot, rename | 3 days |
| 6 | Create horizontal variants for remaining operations | 4 days |
| 7 | Testing: both orientations for all operations, toggle switching | 2 days |

## Open Questions

1. Should the horizontal layout use a specific minimum height threshold (e.g., 200px) below which it falls back to a simplified single-row layout?
2. Should we support a third "compact" layout for very constrained spaces (e.g., mobile bottom sheet)?
3. How do we handle operation-specific widgets (e.g., expression editor, code editor) that don't naturally adapt to horizontal layout?
4. Should the plugin registry support custom third-party operation configs (extensibility for user-defined operations)?
