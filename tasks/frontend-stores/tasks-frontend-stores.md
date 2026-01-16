# Frontend Stores & Schema Calculator

**Parallel Group**: Frontend Core
**Dependencies**: frontend-infrastructure, frontend-api
**Blocks**: frontend-editor, frontend-pipeline

## Relevant Files

- `frontend/src/lib/stores/analysis.svelte.ts` - Analysis state management
- `frontend/src/lib/stores/compute.svelte.ts` - Compute job state management
- `frontend/src/lib/stores/datasource.svelte.ts` - Data source state management
- `frontend/src/lib/utils/schema/polars-types.ts` - Polars dtype definitions
- `frontend/src/lib/utils/schema/transformation-rules.ts` - Schema transformation rules
- `frontend/src/lib/utils/schema/schema-calculator.svelte.ts` - Client-side schema inference
- `frontend/src/lib/utils/schema/schema-calculator.test.ts` - Schema calculator tests

## Tasks

- [x] 8.0 Implement Schema Calculator
  - [x] 8.1 Create `frontend/src/lib/utils/schema/polars-types.ts`:
    - [x] 8.1.1 Define PolarsDataType type with all Polars dtypes:
      - Numeric: Int8, Int16, Int32, Int64, UInt8, UInt16, UInt32, UInt64, Float32, Float64
      - String: Utf8, String
      - Boolean: Boolean
      - Temporal: Date, Time, Datetime, Duration
      - Other: Null, List, Struct, Object
    - [x] 8.1.2 Define dtype category helpers (isNumeric, isString, isTemporal)
    - [x] 8.1.3 Define dtype display names for UI
    - [x] 8.1.4 Define dtype icons/colors for UI
  - [x] 8.2 Create `frontend/src/lib/utils/schema/transformation-rules.ts`:
    - [x] 8.2.1 Define aggregation result types:
      - sum/mean/min/max: same as input (numeric)
      - count: Int64
      - first/last: same as input
      - std/var: Float64
    - [x] 8.2.2 Define expression result type inference (basic)
    - [x] 8.2.3 Define join column merge rules
    - [x] 8.2.4 Export type inference functions
  - [x] 8.3 Create `frontend/src/lib/utils/schema/schema-calculator.svelte.ts`:
    - [x] 8.3.1 Define SchemaCalculator class
    - [x] 8.3.2 Implement `applyFilter(schema, config)`:
      - Filter doesn't change schema
      - Return schema unchanged
    - [x] 8.3.3 Implement `applySelect(schema, config)`:
      - Get selected column names
      - Filter columns to selected only
      - Apply renames if specified
      - Return new schema
    - [x] 8.3.4 Implement `applyRename(schema, config)`:
      - Map old names to new names
      - Return schema with renamed columns
    - [x] 8.3.5 Implement `applyGroupBy(schema, config)`:
      - Get group-by columns
      - Get aggregation definitions
      - Build output columns: group keys + aggregations
      - Infer aggregation result types
      - Return new schema
    - [x] 8.3.6 Implement `applyJoin(leftSchema, rightSchema, config)`:
      - Get join type (inner, left, right, outer)
      - Merge columns from both schemas
      - Handle column name conflicts with suffix
      - Adjust nullability based on join type
      - Return merged schema
    - [x] 8.3.7 Implement `applySort(schema, config)`:
      - Sort doesn't change schema
      - Return schema unchanged
    - [x] 8.3.8 Implement `applyExpression(schema, config)`:
      - Get new column name
      - Infer result type (default to Utf8 if unknown)
      - Add new column to schema
      - Return new schema
    - [x] 8.3.9 Implement `applyWindow(schema, config)`:
      - Get window function and column
      - Infer result type
      - Add new column to schema
      - Return new schema
    - [x] 8.3.10 Implement `calculatePipelineSchema(sourceSchemas, pipeline)`:
      - Start with source schema(s)
      - Iterate through pipeline steps
      - Apply appropriate transformation for each step type
      - Handle DAG by tracking schema per step ID
      - Return final schema
    - [x] 8.3.11 Export singleton instance
  - [ ] 8.4 Write tests in `frontend/src/lib/utils/schema/schema-calculator.test.ts`:
    - [ ] 8.4.1 Test applyFilter returns unchanged schema
    - [ ] 8.4.2 Test applySelect with column subset
    - [ ] 8.4.3 Test applySelect with column rename
    - [ ] 8.4.4 Test applyGroupBy with sum aggregation
    - [ ] 8.4.5 Test applyGroupBy with multiple aggregations
    - [ ] 8.4.6 Test applyJoin inner join
    - [ ] 8.4.7 Test applyJoin left join (nullable right columns)
    - [ ] 8.4.8 Test applyJoin handles column conflicts
    - [ ] 8.4.9 Test applyExpression adds new column
    - [ ] 8.4.10 Test calculatePipelineSchema with multi-step pipeline

- [x] 9.0 Implement Frontend Stores
  - [x] 9.1 Create `frontend/src/lib/stores/analysis.svelte.ts`:
    - [x] 9.1.1 Define AnalysisStore class using Svelte 5 runes:
      ```typescript
      class AnalysisStore {
        current = $state<Analysis | null>(null);
        pipeline = $state<PipelineStep[]>([]);
        sourceSchemas = $state<Map<string, Schema>>(new Map());
        isDirty = $state(false);
        // ... methods
      }
      ```
    - [x] 9.1.2 Define `$derived` computedSchema using SchemaCalculator
    - [x] 9.1.3 Implement `loadAnalysis(id: string)`:
      - Fetch analysis from API
      - Fetch schemas for linked data sources
      - Set current, pipeline, sourceSchemas
      - Set isDirty to false
    - [ ] 9.1.4 Implement `createAnalysis(name, description, datasourceIds)`:
      - Call API to create
      - Load the new analysis
      - Return analysis ID
    - [x] 9.1.5 Implement `addStep(step: PipelineStep)`:
      - Add step to pipeline array
      - Set isDirty to true
    - [x] 9.1.6 Implement `updateStep(id: string, updates: Partial<PipelineStep>)`:
      - Find step by ID
      - Merge updates
      - Set isDirty to true
    - [x] 9.1.7 Implement `removeStep(id: string)`:
      - Filter out step from pipeline
      - Update dependsOn for any dependent steps
      - Set isDirty to true
    - [x] 9.1.8 Implement `reorderSteps(fromIndex, toIndex)`:
      - Move step in array
      - Update dependsOn references
      - Set isDirty to true
    - [x] 9.1.9 Implement `save()`:
      - Call API to update analysis
      - Set isDirty to false
    - [x] 9.1.10 Implement `reset()`:
      - Clear current, pipeline, sourceSchemas
      - Set isDirty to false
    - [x] 9.1.11 Export singleton instance
  - [x] 9.2 Create `frontend/src/lib/stores/compute.svelte.ts`:
    - [x] 9.2.1 Define ComputeStore class:
      ```typescript
      class ComputeStore {
        activeJobs = $state<Map<string, ComputeJob>>(new Map());
        // ... methods
      }
      ```
    - [x] 9.2.2 Implement `executeAnalysis(analysisId: string)`:
      - Call API to start execution
      - Add job to activeJobs
      - Start polling for status
    - [x] 9.2.3 Implement `pollJobStatus(analysisId: string)`:
      - Call API to get status
      - Update job in activeJobs
      - If completed/error, stop polling
      - Return final status
    - [x] 9.2.4 Implement `cancelJob(analysisId: string)`:
      - Call API to cancel
      - Update job status in activeJobs
      - Stop polling
    - [x] 9.2.5 Implement `getJob(analysisId: string)`:
      - Return job from activeJobs or null
    - [x] 9.2.6 Implement `clearJob(analysisId: string)`:
      - Remove job from activeJobs
    - [x] 9.2.7 Export singleton instance
  - [x] 9.3 Create `frontend/src/lib/stores/datasource.svelte.ts`:
    - [x] 9.3.1 Define DataSourceStore class:
      ```typescript
      class DataSourceStore {
        dataSources = $state<DataSourceListItem[]>([]);
        schemas = $state<Map<string, Schema>>(new Map());
        // ... methods
      }
      ```
    - [x] 9.3.2 Implement `loadDataSources()`:
      - Fetch list from API
      - Set dataSources
    - [x] 9.3.3 Implement `uploadFile(file: File, name: string)`:
      - Call API to upload
      - Refresh dataSources list
      - Return new datasource
    - [x] 9.3.4 Implement `getSchema(id: string)`:
      - Check schemas map cache
      - If not cached, fetch from API
      - Cache and return schema
    - [x] 9.3.5 Implement `deleteDataSource(id: string)`:
      - Call API to delete
      - Remove from dataSources
      - Remove from schemas cache
    - [x] 9.3.6 Export singleton instance
  - [x] 9.4 Create `frontend/src/lib/stores/index.ts`:
    - [x] 9.4.1 Export analysisStore
    - [x] 9.4.2 Export computeStore
    - [x] 9.4.3 Export datasourceStore

## Completion Criteria

- [ ] Schema calculator tests pass (tests not written yet)
- [ ] Schema calculation is <100ms for 20-step pipeline (not tested)
- [x] Stores properly track state with Svelte 5 runes
- [ ] isDirty flag updates correctly (not implemented in analysis store)
- [x] Computed schema updates when pipeline changes
- [x] TypeScript compiles without errors
