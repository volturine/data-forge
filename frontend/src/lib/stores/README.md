/\*\*

- Store Usage Examples
-
- These examples demonstrate how to use the Svelte 5 runes-based stores
- in your components.
  \*/

// ============================================================================
// 1. Analysis Store
// ============================================================================

/\*\*

- Example: Load and edit an analysis
  \*/
  import { analysisStore } from '$lib/stores';

// In a component:
async function loadAnalysis(id: string) {
await analysisStore.loadAnalysis(id);
}

// Access reactive state using the store properties directly
const current = analysisStore.current; // Analysis | null
const pipeline = analysisStore.pipeline; // PipelineStep[]
const calculatedSchema = analysisStore.calculatedSchema; // SchemaInfo | null (derived)

// Add a new step
analysisStore.addStep({
id: 'step-1',
type: 'filter',
config: { column: 'age', operator: '>', value: 18 },
depends_on: []
});

// Update a step
analysisStore.updateStep('step-1', {
config: { column: 'age', operator: '>=', value: 21 }
});

// Reorder steps
analysisStore.reorderSteps(0, 2); // Move step from index 0 to 2

// Save changes
await analysisStore.save();

// Set source schema for schema calculation
analysisStore.setSourceSchema('datasource-id', {
columns: [
{ name: 'age', dtype: 'Int64', nullable: false },
{ name: 'name', dtype: 'Utf8', nullable: true }
],
row_count: 1000
});

// ============================================================================
// 2. Compute Store
// ============================================================================

/\*\*

- Example: Execute analysis and monitor progress
  \*/
  import { computeStore } from '$lib/stores';

// Execute an analysis
const job = await computeStore.executeAnalysis('analysis-id');
console.log('Job started:', job.id);

// Get job status (automatically polling if running)
const currentJob = computeStore.getJob(job.id);

// Cancel a job
await computeStore.cancelJob(job.id);

// Manual polling (usually automatic)
await computeStore.pollJobStatus(job.id);

// Clear completed jobs
computeStore.clearJob(job.id);
computeStore.clearAll(); // Clear all jobs

// ============================================================================
// 3. Datasource Store
// ============================================================================

/\*\*

- Example: Manage datasources
  \*/
  import { datasourceStore } from '$lib/stores';

// Load all datasources
await datasourceStore.loadDatasources();

// Access reactive state
const datasources = datasourceStore.datasources; // DataSource[]
const loading = datasourceStore.loading; // boolean
const error = datasourceStore.error; // string | null

// Upload a file
const file = new File(['content'], 'data.csv');
const datasource = await datasourceStore.uploadFile(file, 'My Dataset');

// Get schema (cached)
const schema = await datasourceStore.getSchema('datasource-id');

// Delete a datasource
await datasourceStore.deleteDatasource('datasource-id');

// Find a specific datasource
const ds = datasourceStore.getDatasource('datasource-id');

// Clear schema cache
datasourceStore.clearSchemaCache('datasource-id'); // Clear specific
datasourceStore.clearSchemaCache(); // Clear all

// ============================================================================
// 4. Using in Svelte 5 Components
// ============================================================================

/\*\*

- Full component example using runes
_/
/_
<script lang="ts">
  import { analysisStore, computeStore, datasourceStore } from '$lib/stores';
  import { onMount } from 'svelte';

// Access reactive state directly from stores
const { current, pipeline, calculatedSchema, loading } = analysisStore;
const { datasources } = datasourceStore;
const { jobs } = computeStore;

// Use $effect for side effects (like onMount)
$effect(() => {
datasourceStore.loadDatasources();
});

async function handleExecute() {
if (!current) return;
await computeStore.executeAnalysis(current.id);
}

// Derived state example
const hasJobs = $derived(jobs.size > 0);
const stepCount = $derived(pipeline.length);
</script>

<div>
  {#if loading}
    <p>Loading...</p>
  {:else if current}
    <h2>{current.name}</h2>
    <p>Steps: {stepCount}</p>
    
    {#if calculatedSchema}
      <p>Columns: {calculatedSchema.columns.length}</p>
    {/if}
    
    <button onclick={handleExecute}>Execute</button>
  {/if}
  
  <h3>Datasources ({datasources.length})</h3>
  {#each datasources as ds}
    <div>{ds.name}</div>
  {/each}
</div>
*/

// ============================================================================
// 5. Advanced Pattern: Combining Stores
// ============================================================================

/\*\*

- Example: Build a complete workflow
  \*/
  async function buildAndExecuteAnalysis(datasourceIds: string[]) {
  // 1. Load datasources and their schemas
  await datasourceStore.loadDatasources();

for (const id of datasourceIds) {
const schema = await datasourceStore.getSchema(id);
analysisStore.setSourceSchema(id, schema);
}

// 2. Build pipeline
analysisStore.addStep({
id: crypto.randomUUID(),
type: 'filter',
config: { column: 'status', operator: '==', value: 'active' },
depends_on: []
});

analysisStore.addStep({
id: crypto.randomUUID(),
type: 'select',
config: { columns: ['id', 'name', 'email'] },
depends_on: []
});

// 3. Save analysis
await analysisStore.save();

// 4. Execute
if (analysisStore.current) {
const job = await computeStore.executeAnalysis(analysisStore.current.id);

    // 5. Monitor progress
    return new Promise((resolve, reject) => {
      const checkStatus = () => {
        const currentJob = computeStore.getJob(job.id);
        if (currentJob?.status === 'completed') {
          resolve(currentJob);
        } else if (currentJob?.status === 'failed') {
          reject(new Error(currentJob.error || 'Job failed'));
        }
      };

      // Check every second
      const interval = setInterval(checkStatus, 1000);

      // Cleanup after 5 minutes
      setTimeout(() => {
        clearInterval(interval);
        reject(new Error('Timeout'));
      }, 300000);
    });

}
}
