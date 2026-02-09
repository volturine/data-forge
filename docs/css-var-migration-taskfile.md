# CSS Var Migration Taskfile

Comprehensive task list for removing CSS variable usage from Svelte components and establishing utility-first styling approach

---

Remove all `var(--...)` usage from `frontend/src/**/*.svelte` and avoid JS-computed styles for styling tokens

---

All `.svelte` files in `frontend/src/**/*` containing `var(--...)` references in inline styles, class attributes, or `<style>` blocks

---

No `var(--...)` usage allowed in inline styles, class attributes, or `<style>` blocks; no Tailwind arbitrary `var` classes; avoid JS-computed styles for colors/spacing; allow inline style only for dynamic positioning

---

Refactoring component logic, changing design tokens, performance optimizations, or breaking API changes

---

## Inventory by Area

### Common
ColumnTypeBadge.svelte, LockButton.svelte, FileTypeBadge.svelte, FileBrowser.svelte, MultiSelectColumnDropdown.svelte, DateTimeInput.svelte, DatasourceSelectorModal.svelte, DatasourcePicker.svelte, ConfirmDialog.svelte, CodeEditor.svelte, ColumnTypeSelect.svelte, EngineMonitor.svelte

### Operations
DeduplicateConfig.svelte, GroupByConfig.svelte, PivotConfig.svelte, JoinConfig.svelte, WithColumnsConfig.svelte, RenameConfig.svelte, ExpressionConfig.svelte, FilterConfig.svelte, SortConfig.svelte

### Pipeline
StepNode.svelte, DragPreview.svelte, PipelineCanvas.svelte, StepLibrary.svelte, StepConfig.svelte, DatasourceNode.svelte, ConnectionLine.svelte

### Viewers
InlineDataTable.svelte, DataTable.svelte

### Udfs
UdfEditor.svelte, UdfPickerModal.svelte

### Gallery
AnalysisFilters.svelte

### Datasources
DatasourcePreview.svelte

### Routes
analysis/[id]/+page.svelte, datasources/new/+page.svelte, datasources/+page.svelte, datasources/[id]/+page.svelte, analysis/new/+page.svelte, +layout.svelte, +page.svelte

---

## App.css Utilities

bg-transparent, border-transparent, border-info, text-info-fg, text-info-border, bg-muted, bg-dialog, bg-overlay, bg-accent-bg, bg-info, bg-border-primary, shadow-drag, radius-sm, z-header, panel-width, h-pipeline-connection, code-inline, type-badge classes, file-badge classes, insert-pill classes, confirm dialog classes, CodeMirror classes, shimmer class, analysis header classes, editable title, save-button state, step status, nav-link active

---

## Utilities Still Needed

accent-fg is not defined; recommend using text-accent-primary instead

---

## Per-file Checklist

ColumnTypeBadge: remove `<style>`, use type-badge classes

FileTypeBadge: remove JS style object, use file-badge + size/variant classes

LockButton: remove var border and move lock-btn styles to app.css

FileBrowser: bg-transparent class

MultiSelectColumnDropdown: select-action-btn hover class in app.css

DateTimeInput: clear-btn hover/active class in app.css

DatasourceSelectorModal: replace var classes with utilities, use animate-fade-in/slide-up

DatasourcePicker: picker-option/chip highlight classes

ConfirmDialog: confirm-* classes

CodeEditor: replace var usage in JS theme/highlight with class-based highlight and CSS in app.css

ColumnTypeSelect: replace hover/focus var classes with utilities and replace inline min-width with size classes

EngineMonitor: bg-transparent class

DragPreview: use .drag-preview + .reorder and keep inline left/top only

ConnectionLine: use classes for colors and height

StepNode: move inactive/dashed state to app.css

PipelineCanvas: replace var classes with insert-pill classes

StepLibrary: bg-transparent class

StepConfig: bg-transparent class

DatasourceNode: drag-active style class in app.css

InlineDataTable/DataTable: bg-transparent

UdfEditor/UdfPickerModal: move var styles to app.css

AnalysisFilters: move focus/hover styles to app.css, replace bg-transparent/border-transparent

DatasourcePreview: replace var classes with utilities and address accent-fg

analysis/[id]: move var styles in `<style>` to app.css and replace var classes

datasources/new: + code-inline class, tab active classes

datasources/[id]: tab active

datasources/+page: bg-transparent

analysis/new: step states

+layout: nav-link active

+page: shimmer class in app.css

---

## Validation Steps

Repo-wide grep for `var(--` in svelte

npm run check/build if desired

spot-check UI</content>
<parameter name="filePath">docs/css-var-migration-taskfile.md