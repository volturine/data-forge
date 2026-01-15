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

- [ ] 8.0 Implement Schema Calculator
  - [ ] 8.1 Create `frontend/src/lib/utils/schema/polars-types.ts`:
    - [ ] 8.1.1 Define PolarsDataType type with all Polars dtypes:
      - Numeric: Int8, Int16, Int32, Int64, UInt8, UInt16, UInt32, UInt64, Float32, Float64
      - String: Utf8, String
      - Boolean: Boolean
      - Temporal: Date, Time, Datetime, Duration
      - Other: Null, List, Struct, Object
    - [ ] 8.1.2 Define dtype category helpers (isNumeric, isString, isTemporal)
    - [ ] 8.1.3 Define dtype display names for UI
    - [ ] 8.1.4 Define dtype icons/colors for UI
  - [ ] 8.2 Create `frontend/src/lib/utils/schema/transformation-rules.ts`:
    - [ ] 8.2.1 Define aggregation result types:
      - sum/mean/min/max: same as input (numeric)
      - count: Int64
      - first/last: same as input
      - std/var: Float64
    - [ ] 8.2.2 Define expression result type inference (basic)
    - [ ] 8.2.3 Define join column merge rules
    - [ ] 8.2.4 Export type inference functions
  - [ ] 8.3 Create `frontend/src/lib/utils/schema/schema-calculator.svelte.ts`:
    - [ ] 8.3.1 Define SchemaCalculator class
    - [ ] 8.3.2 Implement `applyFilter(schema, config)`:
      - Filter doesn't change schema
      - Return schema unchanged
    - [ ] 8.3.3 Implement `applySelect(schema, config)`:
      - Get selected column names
      - Filter columns to selected only
      - Apply renames if specified
      - Return new schema
    - [ ] 8.3.4 Implement `applyRename(schema, config)`:
      - Map old names to new names
      - Return schema with renamed columns
    - [ ] 8.3.5 Implement `applyGroupBy(schema, config)`:
      - Get group-by columns
      - Get aggregation definitions
      - Build output columns: group keys + aggregations
      - Infer aggregation result types
      - Return new schema
    - [ ] 8.3.6 Implement `applyJoin(leftSchema, rightSchema, config)`:
      - Get join type (inner, left, right, outer)
      - Merge columns from both schemas
      - Handle column name conflicts with suffix
      - Adjust nullability based on join type
      - Return merged schema
    - [ ] 8.3.7 Implement `applySort(schema, config)`:
      - Sort doesn't change schema
      - Return schema unchanged
    - [ ] 8.3.8 Implement `applyExpression(schema, config)`:
      - Get new column name
      - Infer result type (default to Utf8 if unknown)
      - Add new column to schema
      - Return new schema
    - [ ] 8.3.9 Implement `applyWindow(schema, config)`:
      - Get window function and column
      - Infer result type
      - Add new column to schema
      - Return new schema
    - [ ] 8.3.10 Implement `calculatePipelineSchema(sourceSchemas, pipeline)`:
      - Start with source schema(s)
      - Iterate through pipeline steps
      - Apply appropriate transformation for each step type
      - Handle DAG by tracking schema per step ID
      - Return final schema
    - [ ] 8.3.11 Export singleton instance
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

- [ ] 9.0 Implement Frontend Stores
  - [ ] 9.1 Create `frontend/src/lib/stores/analysis.svelte.ts`:
    - [ ] 9.1.1 Define AnalysisStore class using Svelte 5 runes:
      ```typescript
      class AnalysisStore {
        current = $state<Analysis | null>(null);
        pipeline = $state<PipelineStep[]>([]);
        sourceSchemas = $state<Map<string, Schema>>(new Map());
        isDirty = $state(false);
        // ... methods
      }
      ```
    - [ ] 9.1.2 Define `$derived` computedSchema using SchemaCalculator
    - [ ] 9.1.3 Implement `loadAnalysis(id: string)`:
      - Fetch analysis from API
      - Fetch schemas for linked data sources
      - Set current, pipeline, sourceSchemas
      - Set isDirty to false
    - [ ] 9.1.4 Implement `createAnalysis(name, description, datasourceIds)`:
      - Call API to create
      - Load the new analysis
      - Return analysis ID
    - [ ] 9.1.5 Implement `addStep(step: PipelineStep)`:
      - Add step to pipeline array
      - Set isDirty to true
    - [ ] 9.1.6 Implement `updateStep(id: string, updates: Partial<PipelineStep>)`:
      - Find step by ID
      - Merge updates
      - Set isDirty to true
    - [ ] 9.1.7 Implement `removeStep(id: string)`:
      - Filter out step from pipeline
      - Update dependsOn for any dependent steps
      - Set isDirty to true
    - [ ] 9.1.8 Implement `reorderSteps(fromIndex, toIndex)`:
      - Move step in array
      - Update dependsOn references
      - Set isDirty to true
    - [ ] 9.1.9 Implement `save()`:
      - Call API to update analysis
      - Set isDirty to false
    - [ ] 9.1.10 Implement `reset()`:
      - Clear current, pipeline, sourceSchemas
      - Set isDirty to false
    - [ ] 9.1.11 Export singleton instance
  - [ ] 9.2 Create `frontend/src/lib/stores/compute.svelte.ts`:
    - [ ] 9.2.1 Define ComputeStore class:
      ```typescript
      class ComputeStore {
        activeJobs = $state<Map<string, ComputeJob>>(new Map());
        // ... methods
      }
      ```
    - [ ] 9.2.2 Implement `executeAnalysis(analysisId: string)`:
      - Call API to start execution
      - Add job to activeJobs
      - Start polling for status
    - [ ] 9.2.3 Implement `pollJobStatus(analysisId: string)`:
      - Call API to get status
      - Update job in activeJobs
      - If completed/error, stop polling
      - Return final status
    - [ ] 9.2.4 Implement `cancelJob(analysisId: string)`:
      - Call API to cancel
      - Update job status in activeJobs
      - Stop polling
    - [ ] 9.2.5 Implement `getJob(analysisId: string)`:
      - Return job from activeJobs or null
    - [ ] 9.2.6 Implement `clearJob(analysisId: string)`:
      - Remove job from activeJobs
    - [ ] 9.2.7 Export singleton instance
  - [ ] 9.3 Create `frontend/src/lib/stores/datasource.svelte.ts`:
    - [ ] 9.3.1 Define DataSourceStore class:
      ```typescript
      class DataSourceStore {
        dataSources = $state<DataSourceListItem[]>([]);
        schemas = $state<Map<string, Schema>>(new Map());
        // ... methods
      }
      ```
    - [ ] 9.3.2 Implement `loadDataSources()`:
      - Fetch list from API
      - Set dataSources
    - [ ] 9.3.3 Implement `uploadFile(file: File, name: string)`:
      - Call API to upload
      - Refresh dataSources list
      - Return new datasource
    - [ ] 9.3.4 Implement `getSchema(id: string)`:
      - Check schemas map cache
      - If not cached, fetch from API
      - Cache and return schema
    - [ ] 9.3.5 Implement `deleteDataSource(id: string)`:
      - Call API to delete
      - Remove from dataSources
      - Remove from schemas cache
    - [ ] 9.3.6 Export singleton instance
  - [ ] 9.4 Create `frontend/src/lib/stores/index.ts`:
    - [ ] 9.4.1 Export analysisStore
    - [ ] 9.4.2 Export computeStore
    - [ ] 9.4.3 Export datasourceStore

## Completion Criteria

- [ ] Schema calculator tests pass
- [ ] Schema calculation is <100ms for 20-step pipeline
- [ ] Stores properly track state with Svelte 5 runes
- [ ] isDirty flag updates correctly
- [ ] Computed schema updates when pipeline changes
- [ ] TypeScript compiles without errors
