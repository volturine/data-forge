# Pipeline Components

Components for the visual pipeline builder.

## Overview

The pipeline components form the core of the visual DAG builder, enabling users to create data transformation pipelines through drag-and-drop interactions.

## Components

### PipelineCanvas

**Location:** `frontend/src/lib/components/pipeline/PipelineCanvas.svelte`

The main canvas area where pipeline steps are displayed and manipulated.

#### Props

```typescript
interface Props {
    steps: PipelineStep[];
    datasourceId?: string;
    datasource?: DataSource | null;
    tabName?: string;
    onStepClick: (id: string) => void;
    onStepDelete: (id: string) => void;
    onInsertStep: (type: string, target: DropTarget) => void;
    onMoveStep: (stepId: string, target: DropTarget) => void;
    onChangeDatasource?: () => void;
    onRenameTab?: (name: string) => void;
}
```

#### Features

- **Empty state**: Shows instructions when no steps exist
- **Drop zones**: Visual indicators for valid drop targets
- **Drag validation**: Prevents invalid step placements based on dependencies
- **Connection lines**: Visual links between steps

#### Usage

```svelte
<PipelineCanvas
    {steps}
    {datasourceId}
    {datasource}
    onStepClick={(id) => selectStep(id)}
    onStepDelete={(id) => deleteStep(id)}
    onInsertStep={(type, target) => insertStep(type, target)}
    onMoveStep={(stepId, target) => moveStep(stepId, target)}
/>
```

#### Drop Target Logic

The canvas calculates valid drop positions based on:
- Current step dependencies
- Drag operation type (insert vs reorder)
- Step position constraints

```typescript
interface DropTarget {
    index: number;        // Position in steps array
    parentId: string | null;  // Previous step ID
    nextId: string | null;    // Next step ID
}
```

---

### StepNode

**Location:** `frontend/src/lib/components/pipeline/StepNode.svelte`

Individual step representation in the pipeline with drag handle for reordering.

#### Props

```typescript
interface Props {
    step: PipelineStep;
    index: number;
    datasourceId?: string;
    allSteps?: PipelineStep[];
    onEdit: (id: string) => void;
    onDelete: (id: string) => void;
}
```

#### Features

- **Type display**: Shows operation type with icon and monospace font
- **Config summary**: Brief description of step configuration
- **Drag handle**: 6-dot grip icon for reordering
- **Actions**: Edit and delete buttons
- **View preview**: Inline data preview for `view` steps

#### Step Type Icons

Each step type displays a unique icon:

| Type | Icon |
|------|------|
| filter | 🔍 |
| select | 📋 |
| groupby | 📊 |
| sort | ↕️ |
| rename | ✏️ |
| drop | 🗑️ |
| join | 🔗 |
| expression | 🧮 |
| pivot | 🔄 |
| unpivot | 🔃 |
| fill_null | 🔧 |
| deduplicate | 🧹 |
| explode | 💥 |
| timeseries | 📅 |
| string_transform | 📝 |
| sample | 🎲 |
| limit | ✂️ |
| topk | 🏆 |
| null_count | ❓ |
| value_counts | 📊 |
| view | 👁️ |
| export | 📤 |

#### Drag Events

```typescript
function handleDragStart(event: DragEvent) {
    event.dataTransfer.setData('application/x-pipeline-step', step.id);
    event.dataTransfer.setData('text/plain', step.id);
    event.dataTransfer.effectAllowed = 'move';
    // Custom drag image suppresses native ghost
    if (dragPreviewEl) {
        event.dataTransfer.setDragImage(dragPreviewEl, 0, 0);
    }
    requestAnimationFrame(() => {
        isDragging = true;
        drag.startMove(step.id, step.type);
    });
}
```

#### Drag State

- **Greyed out**: Node is being dragged (opacity 0.4, grayscale filter)
- **Dashed border**: Valid drop target when another node is being dragged

---

### StepLibrary

**Location:** `frontend/src/lib/components/pipeline/StepLibrary.svelte`

Sidebar panel containing available operations.

#### Features

- **Categorized operations**: Grouped by function
- **Draggable items**: Drag to canvas to add new steps
- **Quick insert**: Fallback dropdown controls

#### Categories

| Category | Operations |
|----------|------------|
| Filter | filter, limit, sample, topk |
| Select | select, drop, rename |
| Aggregate | groupby, value_counts, null_count |
| Transform | sort, deduplicate, fill_null, with_columns |
| Reshape | pivot, unpivot, explode |
| String | string_transform |
| Time | timeseries |
| Export | export |
| View | view |

#### Drag Initialization

```typescript
function handleDragStart(event: DragEvent, type: string) {
    event.dataTransfer.setData('application/x-pipeline-step', type);
    event.dataTransfer.setData('text/plain', type);
    event.dataTransfer.effectAllowed = 'copy';
    // Suppress native drag ghost
    if (dragImageEl) {
        event.dataTransfer.setDragImage(dragImageEl, 0, 0);
    }
    requestAnimationFrame(() => {
        isDragging = true;
        drag.start(type, 'library');
    });
}
```

---

### DragPreview

**Location:** `frontend/src/lib/components/pipeline/DragPreview.svelte`

Global floating drag preview that follows cursor during drag operations.

#### Features

- **Floating preview**: Positioned 12px offset from cursor
- **Type-specific**: Shows icon + label for the dragged item
- **Reorder badge**: Displays "Move" badge when reordering existing steps
- **Visual distinction**: Yellow border for reorders, blue for inserts

#### Styling

```css
.drag-preview {
    position: fixed;
    pointer-events: none;
    z-index: 9999;
}

.drag-preview.reorder {
    border-color: #f59e0b;
    background: #fef3c7;
}
```

---

### DatasourceNode

**Location:** `frontend/src/lib/components/pipeline/DatasourceNode.svelte`

The root node displaying the data source.

#### Props

```typescript
interface Props {
    datasource: DataSource;
    tabName?: string;
    onChangeDatasource?: () => void;
    onRenameTab?: (name: string) => void;
}
```

#### Features

- **Non-draggable**: Fixed at pipeline start
- **Name editing**: Inline tab renaming
- **Change button**: Switch data source
- **Schema preview**: Shows column count

---

### ConnectionLine

**Location:** `frontend/src/lib/components/pipeline/ConnectionLine.svelte`

SVG connector between steps.

#### Props

```typescript
interface Props {
    fromStepIndex: number;
    toStepIndex: number;
    totalSteps: number;
    highlighted?: boolean;
}
```

#### Features

- **Animated dash**: Flow direction indicator
- **Highlight state**: Active during drag operations
- **Responsive**: Adjusts to step positions

---

### StepConfig

**Location:** `frontend/src/lib/components/pipeline/StepConfig.svelte`

Configuration panel for the selected step.

#### Props

```typescript
interface Props {
    step: PipelineStep | null;
    schema: Schema | null;
    onConfigChange: (config: Record<string, unknown>) => void;
}
```

#### Features

- **Dynamic component**: Loads appropriate config component
- **Schema awareness**: Uses dependency chain to calculate input schema
- **Debounced save**: Auto-saves with delay

#### Schema Calculation

The component builds a dependency chain from root to the parent step:

```typescript
const parentId = step.depends_on?.[0] ?? null;
// Walk up the dependency tree to build the chain
while (currentId) {
    const currentStep = stepMap.get(currentId);
    dependencyChain.unshift(currentStep);
    currentId = currentStep.depends_on?.[0] ?? null;
}
```

#### Component Mapping

```typescript
const configComponents: Record<string, Component> = {
    filter: FilterConfig,
    select: SelectConfig,
    groupby: GroupByConfig,
    sort: SortConfig,
    rename: RenameConfig,
    drop: DropConfig,
    // ... more mappings
};
```

---

## State Integration

### Drag Store

**Location:** `frontend/src/lib/stores/drag.svelte.ts`

Centralized drag state for pipeline operations.

```typescript
class DragState {
    type = $state<string | null>(null);        // Step type (for library drags)
    stepId = $state<string | null>(null);      // Step ID (for canvas reorders)
    source = $state<DragSource | null>(null);  // 'library' or 'canvas'
    target = $state<DropTarget | null>(null);  // Current drop target
    valid = $state(true);                      // Is target valid?

    active = $derived(this.type !== null || this.stepId !== null);
    isReorder = $derived(this.source === 'canvas' && this.stepId !== null);
    isInsert = $derived(this.source === 'library' && this.type !== null);

    start(type: string, source: DragSource) { /* ... */ }
    startMove(stepId: string, type: string) { /* ... */ }
    setTarget(target: DropTarget, valid: boolean) { /* ... */ }
    clearTarget() { /* ... */ }
    end() { /* ... */ }
}

export const drag = new DragState();
```

#### Usage

```typescript
// Library drag
drag.start('filter', 'library');

// Canvas reorder
drag.startMove('step-uuid', 'filter');

// On drop
if (drag.isReorder && drag.stepId) {
    onMoveStep(drag.stepId, drag.target);
} else if (drag.isInsert && drag.type) {
    onInsertStep(drag.type, drag.target);
}
drag.end();
```

---

### Analysis Store

Steps are managed via the analysis store:

```typescript
// Adding a step
analysisStore.addStep(tabId, {
    id: crypto.randomUUID(),
    type: 'filter',
    config: { conditions: [], logic: 'AND' },
    depends_on: [parentId]
});

// Moving a step
analysisStore.moveStep(tabId, stepId, newIndex, newDependsOn);

// Updating config
analysisStore.updateStepConfig(stepId, newConfig);
```

---

## Styling

### CSS Variables

Pipeline components use these design tokens:

```css
/* Backgrounds */
--bg-primary: #ffffff;
--bg-secondary: #f9fafb;
--bg-tertiary: #f3f4f6;

/* Borders */
--border-primary: #e5e7eb;
--border-tertiary: #9ca3af;

/* Accents */
--accent-primary: #3b82f6;
--accent-soft: rgba(59, 130, 246, 0.1);

/* Spacing */
--space-2: 0.5rem;
--space-4: 1rem;
--space-6: 1.5rem;
```

### Animations

```css
/* Drag handle */
.drag-handle {
    opacity: 0.4;
    transition: opacity 0.15s;
}

.drag-handle:hover {
    opacity: 1;
}

/* Node drag state */
.step-node.greyed-out {
    opacity: 0.4;
    filter: grayscale(50%);
}

/* Drop slot activation */
.drop-slot.active {
    border-color: var(--fg-primary);
    background-color: var(--bg-tertiary);
}

/* Hover lift */
.step-content:hover {
    transform: translateY(-1px);
}
```

---

## Accessibility

- **Keyboard navigation**: Tab through steps
- **ARIA roles**: `role="list"`, `role="listitem"`
- **Focus indicators**: Visible focus states
- **Screen reader labels**: Descriptive button labels
- **Drag handle**: Title attribute "Drag to reorder"

---

## See Also

- [Operations Components](../operations/README.md) - Config components
- [State Management](../../state-management/README.md) - Store patterns
- [Building Pipelines](../../../guides/building-pipelines.md) - User guide
