# State Management

Documentation for reactive state management using Svelte 5 runes.

## Overview

The application uses Svelte 5 runes for state management. State is organized into class-based stores using `$state`, `$derived`, and `$effect`.

## Svelte 5 Runes

### $state

Declares reactive state:

```typescript
class Store {
    // Primitive state
    count = $state(0);

    // Object state
    user = $state<User | null>(null);

    // Array state
    items = $state<Item[]>([]);

    // Map state (needs manual reactivity trigger)
    cache = $state(new Map<string, Data>());
}
```

### $derived

Computed values that auto-update:

```typescript
class Store {
    items = $state<Item[]>([]);

    // Simple derived
    count = $derived(this.items.length);

    // Complex derived with .by()
    filtered = $derived.by(() => {
        return this.items.filter(item => item.active);
    });
}
```

### $effect

Side effects that run when dependencies change:

```svelte
<script lang="ts">
    let count = $state(0);

    $effect(() => {
        console.log(`Count changed to: ${count}`);
        // Cleanup function (optional)
        return () => {
            console.log('Cleaning up...');
        };
    });
</script>
```

## Store Architecture

### Class-Based Stores

```typescript
// stores/analysis.svelte.ts
export class AnalysisStore {
    // State
    current = $state<Analysis | null>(null);
    loading = $state(false);
    error = $state<string | null>(null);

    // Derived
    isLoaded = $derived(this.current !== null);

    // Methods
    async load(id: string): Promise<void> {
        this.loading = true;
        try {
            this.current = await getAnalysis(id);
        } catch (err) {
            this.error = err.message;
        } finally {
            this.loading = false;
        }
    }

    reset(): void {
        this.current = null;
        this.error = null;
    }
}

// Export singleton instance
export const analysisStore = new AnalysisStore();
```

### File Naming Convention

Store files use `.svelte.ts` extension to enable runes:

```
stores/
├── analysis.svelte.ts    # ✓ Runes enabled
├── datasource.svelte.ts  # ✓ Runes enabled
├── compute.svelte.ts     # ✓ Runes enabled
├── drag.svelte.ts        # ✓ Runes enabled
└── index.ts              # Re-exports
```

## Available Stores

### AnalysisStore

Manages current analysis and pipeline state.

```typescript
class AnalysisStore {
    // State
    current = $state<Analysis | null>(null);
    tabs = $state<AnalysisTab[]>([]);
    activeTabId = $state<string | null>(null);
    sourceSchemas = $state(new Map<string, SchemaInfo>());
    loading = $state(false);
    error = $state<string | null>(null);

    // Derived
    activeTab = $derived.by(() => {
        return this.tabs.find(tab => tab.id === this.activeTabId) ?? null;
    });

    pipeline = $derived.by(() => {
        return this.activeTab?.steps ?? [];
    });

    calculatedSchema = $derived.by(() => {
        // Calculate schema from pipeline steps
        return schemaCalculator.calculatePipelineSchema(baseSchema, this.pipeline);
    });

    // Methods
    async loadAnalysis(id: string): Promise<void>;
    async save(): Promise<void>;
    addStep(step: PipelineStep): void;
    updateStep(id: string, updates: Partial<PipelineStep>): void;
    removeStep(id: string): void;
    setActiveTab(id: string): void;
    reset(): void;
}
```

**Usage**:

```svelte
<script lang="ts">
    import { analysisStore } from '$lib/stores';

    $effect(() => {
        analysisStore.loadAnalysis(analysisId);
    });
</script>

{#if analysisStore.loading}
    <Loading />
{:else if analysisStore.current}
    <Pipeline steps={analysisStore.pipeline} />
{/if}
```

### DatasourceStore

Manages datasource list and operations.

```typescript
class DatasourceStore {
    items = $state<DataSource[]>([]);
    loading = $state(false);
    error = $state<string | null>(null);

    async loadAll(): Promise<void>;
    async delete(id: string): Promise<void>;
}
```

### ComputeStore

Manages pipeline execution state.

```typescript
class ComputeStore {
    jobId = $state<string | null>(null);
    status = $state<JobStatus>('idle');
    progress = $state(0);
    currentStep = $state<string | null>(null);
    result = $state<ComputeResult | null>(null);
    error = $state<string | null>(null);

    isRunning = $derived(this.status === 'running');

    async execute(analysisId: string, tabId: string): Promise<void>;
    async pollStatus(): Promise<void>;
    reset(): void;
}
```

### DragStore

Manages drag-and-drop state for pipeline builder.

```typescript
type DragSource = 'library' | 'canvas';

interface DropTarget {
    index: number;
    parentId: string | null;
    nextId: string | null;
}

class DragState {
    type = $state<string | null>(null);        // Step type (for library drags)
    stepId = $state<string | null>(null);      // Step ID (for canvas reorders)
    source = $state<DragSource | null>(null);  // 'library' or 'canvas'
    target = $state<DropTarget | null>(null);  // Current drop target
    valid = $state(true);                      // Is target valid?

    active = $derived(this.type !== null || this.stepId !== null);
    isReorder = $derived(this.source === 'canvas' && this.stepId !== null);
    isInsert = $derived(this.source === 'library' && this.type !== null);

    start(type: string, source: DragSource): void;
    startMove(stepId: string, type: string): void;
    setTarget(target: DropTarget, valid: boolean): void;
    clearTarget(): void;
    end(): void;
}

export const drag = new DragState();
```

#### Usage

```typescript
// Library drag
drag.start('filter', 'library');

// Canvas reorder
drag.startMove('step-uuid', 'filter');

// Check drag state
if (drag.isReorder) {
    // Reordering existing step
} else if (drag.isInsert) {
    // Adding new step from library
}

// Update drop target
drag.setTarget({ index: 2, parentId: 'prev-step', nextId: 'next-step' }, true);

// End drag
drag.end();
```

## Usage Patterns

### Loading Data

```svelte
<script lang="ts">
    import { analysisStore } from '$lib/stores';

    let { analysisId } = $props();

    $effect(() => {
        analysisStore.loadAnalysis(analysisId);

        return () => {
            analysisStore.reset();
        };
    });
</script>
```

### Conditional Rendering

```svelte
{#if analysisStore.loading}
    <div class="loading">Loading...</div>
{:else if analysisStore.error}
    <div class="error">{analysisStore.error}</div>
{:else if analysisStore.current}
    <AnalysisEditor analysis={analysisStore.current} />
{/if}
```

### Form Binding

```svelte
<script lang="ts">
    let name = $state('');
    let description = $state('');

    async function handleSubmit() {
        await analysisStore.create({ name, description });
    }
</script>

<form onsubmit={handleSubmit}>
    <input bind:value={name} />
    <textarea bind:value={description}></textarea>
    <button type="submit">Create</button>
</form>
```

### Watching Changes

```svelte
<script lang="ts">
    import { analysisStore } from '$lib/stores';

    // Auto-save when pipeline changes
    $effect(() => {
        const pipeline = analysisStore.pipeline;
        if (pipeline.length > 0) {
            // Debounce save
            const timer = setTimeout(() => {
                analysisStore.save();
            }, 1000);

            return () => clearTimeout(timer);
        }
    });
</script>
```

## Map Reactivity

Maps need manual reactivity triggers:

```typescript
class Store {
    cache = $state(new Map<string, Data>());

    setItem(key: string, value: Data): void {
        this.cache.set(key, value);
        // Trigger reactivity by reassignment
        this.cache = new Map(this.cache);
    }

    deleteItem(key: string): void {
        this.cache.delete(key);
        this.cache = new Map(this.cache);
    }
}
```

## TanStack Query Integration

For server state, use TanStack Query alongside stores:

```svelte
<script lang="ts">
    import { createQuery } from '@tanstack/svelte-query';
    import { listAnalyses } from '$lib/api/analysis';

    const query = createQuery({
        queryKey: ['analyses'],
        queryFn: listAnalyses
    });
</script>

{#if $query.isLoading}
    <Loading />
{:else if $query.error}
    <Error message={$query.error.message} />
{:else}
    {#each $query.data as analysis}
        <AnalysisCard {analysis} />
    {/each}
{/if}
```

## Best Practices

### 1. Separate Concerns

- **Stores**: Application state
- **TanStack Query**: Server state / caching
- **Local state**: Component-specific UI state

### 2. Keep Stores Simple

```typescript
// Good: Simple, focused store
class CounterStore {
    count = $state(0);
    increment() { this.count++; }
    decrement() { this.count--; }
}

// Bad: Doing too much
class EverythingStore {
    users = $state([]);
    posts = $state([]);
    comments = $state([]);
    // ... mixing unrelated concerns
}
```

### 3. Use Derived for Computed Values

```typescript
// Good: Derived value
filtered = $derived.by(() => {
    return this.items.filter(i => i.active);
});

// Bad: Manually updating
updateFiltered() {
    this.filtered = this.items.filter(i => i.active);
}
```

### 4. Handle Async Properly

```typescript
async load(id: string): Promise<void> {
    this.loading = true;
    this.error = null;

    try {
        this.data = await fetchData(id);
    } catch (err) {
        this.error = err instanceof Error ? err.message : 'Unknown error';
    } finally {
        this.loading = false;
    }
}
```

## See Also

- [Svelte 5 Runes](https://svelte.dev/docs/svelte/$state) - Official documentation
- [API Client](../api-client/README.md) - HTTP layer
- [Components](../components/README.md) - Component documentation
