# Gallery Components

Components for the analysis gallery view.

## Overview

Gallery components display the list of saved analyses, providing navigation to the pipeline editor and management capabilities.

## Components

### GalleryGrid

**Location:** `frontend/src/lib/components/gallery/GalleryGrid.svelte`

Grid layout container for analysis cards.

#### Props

```typescript
interface Props {
  analyses: AnalysisGalleryItem[];
  loading?: boolean;
  onDelete: (id: string) => void;
}
```

#### Features

- **Responsive grid**: Adapts to screen size
- **Loading state**: Skeleton cards
- **Empty handling**: Delegates to EmptyState

#### Grid Layout

```css
.gallery-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--space-6);
  padding: var(--space-6);
}

/* Responsive breakpoints */
@media (max-width: 640px) {
  .gallery-grid {
    grid-template-columns: 1fr;
  }
}
```

#### Usage

```svelte
<GalleryGrid
    analyses={analysisItems}
    loading={isLoading}
    onDelete={(id) => handleDelete(id)}
/>
```

---

### AnalysisCard

**Location:** `frontend/src/lib/components/gallery/AnalysisCard.svelte`

Individual analysis card with preview and actions.

#### Props

```typescript
interface Props {
  analysis: AnalysisGalleryItem;
  onDelete: (id: string) => void;
}
```

#### Data Structure

```typescript
interface AnalysisGalleryItem {
  id: string;
  name: string;
  thumbnail: string | null;
  created_at: string;
  updated_at: string;
  row_count: number | null;
  column_count: number | null;
}
```

#### Features

- **Thumbnail**: Image preview or placeholder icon
- **Metadata**: Row/column counts, date
- **Click navigation**: Opens analysis editor
- **Delete button**: Removes analysis
- **Hover effects**: Subtle lift animation

#### Navigation

```typescript
function handleClick(e: MouseEvent) {
  // Don't navigate if clicking delete button
  if (!(e.target as HTMLElement).closest("button")) {
    goto(`/analysis/${analysis.id}`, { invalidateAll: true });
  }
}
```

#### Date Formatting

```typescript
function formatDate(date: string): string {
  return new Date(date).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}
```

#### Styling

```css
.card {
  border: 1px solid var(--border-primary);
  border-radius: var(--radius-sm);
  overflow: hidden;
  cursor: pointer;
  transition: all var(--transition);
  background-color: var(--bg-primary);
  box-shadow: var(--card-shadow);
}

.card:hover {
  border-color: var(--border-tertiary);
  transform: translateY(-1px);
}

.thumbnail {
  width: 100%;
  aspect-ratio: 16 / 9;
  background-color: var(--bg-tertiary);
}

.btn-delete:hover {
  background-color: var(--error-bg);
  border-color: var(--error-border);
  color: var(--error-fg);
}
```

---

### AnalysisFilters

**Location:** `frontend/src/lib/components/gallery/AnalysisFilters.svelte`

Filtering and sorting controls for the gallery.

#### Props

```typescript
interface Props {
  sortBy: "name" | "updated_at" | "created_at";
  sortDirection: "asc" | "desc";
  searchQuery: string;
  onSortChange: (sortBy: string, direction: string) => void;
  onSearchChange: (query: string) => void;
}
```

#### Features

- **Search input**: Filter by name
- **Sort dropdown**: Name, updated, created
- **Direction toggle**: Ascending/descending
- **Debounced search**: Prevents excessive filtering

#### Usage

```svelte
<AnalysisFilters
    {sortBy}
    {sortDirection}
    {searchQuery}
    onSortChange={(by, dir) => updateSort(by, dir)}
    onSearchChange={(q) => updateSearch(q)}
/>
```

---

### EmptyState

**Location:** `frontend/src/lib/components/gallery/EmptyState.svelte`

Placeholder when no analyses exist.

#### Props

```typescript
interface Props {
  onCreate: () => void;
}
```

#### Features

- **Icon**: Visual indicator
- **Message**: Instructional text
- **CTA button**: Create first analysis

#### Styling

```css
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-12);
  text-align: center;
  color: var(--fg-muted);
}

.empty-state h3 {
  margin: var(--space-4) 0 var(--space-2);
  color: var(--fg-secondary);
}

.create-btn {
  margin-top: var(--space-6);
  padding: var(--space-3) var(--space-6);
  background-color: var(--accent-primary);
  color: white;
  border: none;
  border-radius: var(--radius-md);
  cursor: pointer;
}
```

---

## Page Integration

### Gallery Page Structure

```svelte
<!-- routes/+page.svelte -->
<script lang="ts">
    import { GalleryGrid, AnalysisFilters, EmptyState } from '$lib/components/gallery';
    import { analysisStore } from '$lib/stores/analysis.svelte';
    import { createQuery } from '@tanstack/svelte-query';

    const analysesQuery = createQuery({
        queryKey: ['analyses'],
        queryFn: () => fetchAnalyses()
    });

    let sortBy = $state('updated_at');
    let sortDirection = $state('desc');
    let searchQuery = $state('');

    // Filtered and sorted analyses
    let displayedAnalyses = $derived(
        filterAndSort(
            $analysesQuery.data ?? [],
            searchQuery,
            sortBy,
            sortDirection
        )
    );
</script>

<div class="gallery-page">
    <header>
        <h1>My Analyses</h1>
        <button onclick={createNewAnalysis}>New Analysis</button>
    </header>

    <AnalysisFilters
        {sortBy}
        {sortDirection}
        {searchQuery}
        onSortChange={(by, dir) => { sortBy = by; sortDirection = dir; }}
        onSearchChange={(q) => { searchQuery = q; }}
    />

    {#if $analysesQuery.isLoading}
        <GalleryGrid analyses={[]} loading={true} onDelete={() => {}} />
    {:else if displayedAnalyses.length === 0 && !searchQuery}
        <EmptyState onCreate={createNewAnalysis} />
    {:else}
        <GalleryGrid
            analyses={displayedAnalyses}
            onDelete={handleDelete}
        />
    {/if}
</div>
```

---

## State Management

### Analysis Store Integration

```typescript
// Creating new analysis
async function createNewAnalysis() {
  const result = await createAnalysis({
    name: "Untitled Analysis",
    datasource_ids: [],
    pipeline_steps: [],
    tabs: [],
  });

  if (result.isOk()) {
    goto(`/analysis/${result.value.id}`);
  }
}

// Deleting analysis
async function handleDelete(id: string) {
  if (confirm("Delete this analysis?")) {
    await deleteAnalysis(id);
    // Invalidate query to refresh list
  }
}
```

### TanStack Query

```typescript
import { createQuery, useQueryClient } from "@tanstack/svelte-query";

const queryClient = useQueryClient();

// After delete, invalidate the list
queryClient.invalidateQueries({ queryKey: ["analyses"] });
```

---

## Accessibility

- **Card interaction**: `role="button"`, `tabindex="0"`
- **Keyboard navigation**: Enter/Space to open
- **Delete confirmation**: Prevents accidental deletion
- **Focus management**: Visible focus states
- **Screen reader labels**: Descriptive button labels

---

## Responsive Design

| Breakpoint      | Columns | Card Width |
| --------------- | ------- | ---------- |
| < 640px         | 1       | 100%       |
| 640px - 1024px  | 2       | ~280px     |
| 1024px - 1280px | 3       | ~280px     |
| > 1280px        | 4+      | ~280px     |

---

## See Also

- [Pipeline Components](../pipeline/README.md) - Pipeline editor
- [State Management](../../state-management/README.md) - Analysis store
- [API Client](../../api-client/README.md) - API integration
