# CSS Variable Migration Taskfile

## Objective
Migrate all `var(--...)` usage from `.svelte` files to use CSS utility classes defined in `app.css`, ensuring consistent styling and maintainability across the application.

## Scope
All `.svelte` files in `frontend/src/**/*` containing `var(--...)` references in:
- Inline styles (`style="..."`)
- Class attributes with Tailwind utilities using `var(--...)`
- `<style>` blocks

## Constraints
- No `var(--...)` usage allowed in `.svelte` files
- Must use existing utility classes from `app.css`
- Add new utility classes only if absolutely necessary
- Preserve all visual styling and behavior

## Non-goals
- Refactoring component logic or structure
- Changing design tokens in `app.css`
- Performance optimizations beyond the migration
- Breaking changes to component APIs

## Inventory of Affected Areas

### Common Components (4 files)
- `ColumnTypeBadge.svelte` - Type color styling
- `LockButton.svelte` - Button states and colors
- `FileTypeBadge.svelte` - File type colors
- `FileBrowser.svelte` - Link and button styling

### Operations Components (2 files)
- `DeduplicateConfig.svelte` - Border and background colors
- `GroupByConfig.svelte` - Border and background colors

### Pipeline Components (2 files)
- `StepNode.svelte` - Node styling and interactions
- `DragPreview.svelte` - Drag preview appearance
- `PipelineCanvas.svelte` - Canvas styling and states

### Viewers (2 files)
- `InlineDataTable.svelte` - Table row styling
- `DataTable.svelte` - Table row styling

### UDF Components (1 file)
- `UdfEditor.svelte` - Editor container styling

### Routes (1 file)
- `analysis/[id]/+page.svelte` - Header and tab styling

Total: 13 files with ~100+ var(--...) usages

## app.css Utility Additions
Most required utilities already exist. Add these if needed:

```css
/* Missing utility classes (if any) */
.font-mono {
  font-family: var(--font-mono);
}

.z-header {
  z-index: var(--z-header);
}

.panel-width {
  width: var(--operations-panel-width, 280px);
  transition: width var(--transition), visibility var(--transition);
}

.space-1 {
  margin: var(--space-1);
}

.animate-fade-in {
  animation: var(--animate-fade-in);
}
```

## Per-file Checklist

### Common Components

#### ColumnTypeBadge.svelte
- [ ] Replace `<style>` block var(--font-mono) with `.font-mono` class
- [ ] Replace all type color vars (--type-*-fg/bg/border) with `.type-badge.category-*` classes
- [ ] Replace `--color-transparent` with `.bg-transparent` class

#### LockButton.svelte
- [ ] Replace `border-[var(--color-transparent)]` with `border-transparent`
- [ ] Replace `background: var(--warning-border)` with `.bg-warning-border`
- [ ] Replace `background: var(--accent-primary)` with `.bg-accent-primary`
- [ ] Replace `color: var(--warning-contrast)` with `.text-warning-contrast`
- [ ] Replace `background: var(--bg-tertiary)` with `.bg-tertiary`
- [ ] Replace `color: var(--fg-muted)` with `.text-fg-muted`

#### FileTypeBadge.svelte
- [ ] Replace ternary `var(--color-transparent)` with conditional classes `.bg-transparent`

#### FileBrowser.svelte
- [ ] Replace `bg-[var(--color-transparent)]` with `bg-transparent`
- [ ] Replace `text-accent` with `text-accent-primary`

### Operations Components

#### DeduplicateConfig.svelte
- [ ] Replace `border-color: var(--info-border)` with `border-info`
- [ ] Replace `background-color: var(--bg-hover)` with `bg-hover`

#### GroupByConfig.svelte
- [ ] Replace `background-color: var(--bg-muted)` with `bg-muted`
- [ ] Replace `color: var(--fg-muted)` with `text-fg-muted`
- [ ] Replace `border: 1px solid var(--border-primary)` with `border-primary`

### Pipeline Components

#### StepNode.svelte
- [ ] Replace `bg-[var(--color-transparent)]` with `bg-transparent`
- [ ] Replace `bg-[var(--bg-tertiary)]` with `bg-tertiary`
- [ ] Replace `border-[var(--border-primary)]` with `border-primary`
- [ ] Replace `bg-[var(--bg-secondary)]` with `bg-secondary`
- [ ] Replace `color: var(--fg-muted)` with `text-fg-muted`
- [ ] Replace `background-color: var(--bg-tertiary)` with `bg-tertiary`
- [ ] Replace `color: var(--fg-secondary)` with `text-fg-secondary`
- [ ] Replace `border-color: var(--info-border)` with `border-info`

#### DragPreview.svelte
- [ ] Replace `background: var(--bg-primary)` with `bg-primary`
- [ ] Replace `border-color: var(--info-border)` with `border-info`
- [ ] Replace `box-shadow: var(--shadow-drag)` with `shadow-drag`
- [ ] Replace `background: var(--warning-bg)` with `bg-warning`
- [ ] Replace `border-color: var(--warning-border)` with `border-warning`

#### PipelineCanvas.svelte
- [ ] Replace all `bg-[var(--color-transparent)]` with `bg-transparent`
- [ ] Replace all `border-[var(--border-primary)]` with `border-primary`
- [ ] Replace all `bg-[var(--bg-hover)]` with `bg-hover`
- [ ] Replace all `border-[var(--info-border)]` with `border-info`
- [ ] Replace all `bg-[var(--bg-tertiary)]` with `bg-tertiary`
- [ ] Replace all `border-[var(--error-border)]` with `border-error`
- [ ] Replace all `bg-[var(--error-bg)]` with `bg-error`
- [ ] Replace `text-[var(--fg-primary)]` with `text-fg-primary`

### Viewers

#### InlineDataTable.svelte
- [ ] Replace `bg-[var(--color-transparent)]` with `bg-transparent`

#### DataTable.svelte
- [ ] Replace `bg-[var(--color-transparent)]` with `bg-transparent`

### UDF Components

#### UdfEditor.svelte
- [ ] Replace `background-color: var(--bg-tertiary)` with `bg-tertiary`
- [ ] Replace `border: 1px solid var(--border-primary)` with `border-primary`
- [ ] Replace `border-radius: var(--radius-sm)` with `radius-sm`
- [ ] Replace `color: var(--fg-secondary)` with `text-fg-secondary`
- [ ] Replace `background-color: var(--bg-hover)` with `bg-hover`
- [ ] Replace `color: var(--fg-primary)` with `text-fg-primary`

### Routes

#### analysis/[id]/+page.svelte
- [ ] Replace `bg-[var(--color-transparent)]` (multiple instances) with `bg-transparent`
- [ ] Replace `text-fg-muted` (already correct, verify)
- [ ] Replace `bg-hover` (already correct, verify)
- [ ] Replace `border-primary` (already correct, verify)
- [ ] Replace `text-fg-primary` (already correct, verify)
- [ ] Replace `bg-[var(--bg-hover)]` with `bg-hover`
- [ ] Replace `border-[var(--border-primary)]` with `border-primary`
- [ ] Replace `border-[var(--info-border)]` with `border-info`
- [ ] Replace `bg-[var(--bg-tertiary)]` with `bg-tertiary`
- [ ] Replace `color: var(--success-fg)` with `text-success`
- [ ] Replace `background-color: var(--warning-bg)` with `bg-warning`
- [ ] Replace `color: var(--warning-fg)` with `text-warning`
- [ ] Replace `border-left: 1px solid var(--warning-border)` with `border-warning`
- [ ] Replace `color: var(--fg-primary)` with `text-fg-primary`
- [ ] Replace `background-color: var(--bg-secondary)` with `bg-secondary`
- [ ] Replace `transition: visibility var(--transition)` with `transition` class or inline
- [ ] Replace `z-index: var(--z-header)` with `z-header`
- [ ] Replace `width: var(--operations-panel-width, 280px)` with `panel-width`
- [ ] Replace `transition: width var(--transition)` with part of `panel-width` class

## Validation Steps
1. **Build Check**: Run `npm run build` to ensure no CSS compilation errors
2. **Visual Regression**: Manually test each component for visual changes
3. **Grep Verification**: Confirm `grep -r "var(--" frontend/src/**/*.svelte` returns no results
4. **Utility Coverage**: Verify all used CSS variables have corresponding utility classes
5. **Dark/Light Mode**: Test theme switching on affected components
6. **Responsive Design**: Check mobile/tablet layouts for pipeline and analysis pages
7. **Performance**: Ensure no impact on bundle size or runtime performance</content>
<parameter name="filePath">docs/css-var-migration-taskfile.md