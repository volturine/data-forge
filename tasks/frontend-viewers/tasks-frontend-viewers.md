# Frontend Data Viewers

**Parallel Group**: Frontend Components
**Dependencies**: frontend-infrastructure
**Blocks**: frontend-editor

## Relevant Files

- `frontend/src/lib/components/viewers/SchemaViewer.svelte` - Schema display
- `frontend/src/lib/components/viewers/DataTable.svelte` - Virtualized data table
- `frontend/src/lib/components/viewers/StatsPanel.svelte` - Summary statistics
- `frontend/src/lib/components/viewers/DataChart.svelte` - Chart visualizations

## Tasks

- [ ] 12.0 Implement Data Viewers
  - [ ] 12.1 Create `frontend/src/lib/components/viewers/SchemaViewer.svelte`:
    - [ ] 12.1.1 Define props: schema (Schema), compact (boolean, default false)
    - [ ] 12.1.2 Display header with column count
    - [ ] 12.1.3 Render column list:
      - Column name
      - Data type with icon
      - Nullable indicator
    - [ ] 12.1.4 Implement compact mode (horizontal chips)
    - [ ] 12.1.5 Implement full mode (vertical list with details)
    - [ ] 12.1.6 Add type icons for each Polars dtype category:
      - Numeric: # icon
      - String: Abc icon
      - Boolean: checkbox icon
      - Temporal: calendar icon
      - Other: ? icon
    - [ ] 12.1.7 Style with proper spacing and colors
  - [ ] 12.2 Create `frontend/src/lib/components/viewers/DataTable.svelte`:
    - [ ] 12.2.1 Define props:
      - columns: string[]
      - data: Record<string, unknown>[]
      - totalRows: number
      - isLoading: boolean
      - onPageChange: (offset: number) => void
      - onSort: (column: string, desc: boolean) => void
    - [ ] 12.2.2 Implement table header:
      - Column names
      - Sort indicators
      - Click to sort
    - [ ] 12.2.3 Implement table body:
      - Render rows with proper cell formatting
      - Handle null values display
      - Format numbers, dates appropriately
    - [ ] 12.2.4 Implement virtual scrolling (or pagination):
      - Show page size selector (25, 50, 100)
      - Page navigation buttons
      - Current page / total pages indicator
    - [ ] 12.2.5 Implement column resizing (optional)
    - [ ] 12.2.6 Loading state: skeleton rows
    - [ ] 12.2.7 Empty state: "No data" message
    - [ ] 12.2.8 Style with alternating row colors
  - [ ] 12.3 Create `frontend/src/lib/components/viewers/StatsPanel.svelte`:
    - [ ] 12.3.1 Define props:
      - schema: Schema
      - rowCount: number
      - columnCount: number
      - fileSize?: number
    - [ ] 12.3.2 Display overview stats:
      - Total rows
      - Total columns
      - File size (formatted)
    - [ ] 12.3.3 Display column type breakdown:
      - Count of numeric columns
      - Count of string columns
      - Count of temporal columns
      - Count of other columns
    - [ ] 12.3.4 Style as compact stat cards
  - [ ] 12.4 Create `frontend/src/lib/components/viewers/DataChart.svelte`:
    - [ ] 12.4.1 Define props:
      - data: Record<string, unknown>[]
      - columns: string[]
      - chartType: 'bar' | 'line' | 'scatter'
    - [ ] 12.4.2 Add chart configuration controls:
      - Chart type selector
      - X-axis column dropdown
      - Y-axis column dropdown (numeric columns only)
      - Color/group by column (optional)
    - [ ] 12.4.3 Implement basic chart rendering:
      - Use Canvas or SVG
      - Or integrate chart library (Chart.js, etc.)
    - [ ] 12.4.4 Handle empty/invalid data gracefully
    - [ ] 12.4.5 Add chart title and legend
    - [ ] 12.4.6 Responsive sizing

## Completion Criteria

- [ ] SchemaViewer displays columns with correct types and icons
- [ ] DataTable renders data with sorting
- [ ] DataTable pagination works correctly
- [ ] StatsPanel shows correct statistics
- [ ] DataChart renders basic charts
- [ ] All components handle loading/empty states
- [ ] Components are responsive
