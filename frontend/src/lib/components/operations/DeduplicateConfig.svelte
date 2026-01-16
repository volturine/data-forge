<script lang="ts">
	import type { Schema } from '$lib/types/schema';

	interface DeduplicateConfigData {
		subset: string[] | null;
		keep: string;
	}

	interface Props {
		schema: Schema;
		config: DeduplicateConfigData;
		onSave: (config: DeduplicateConfigData) => void;
	}

	let { schema, config, onSave }: Props = $props();

	let localConfig = $state<DeduplicateConfigData>({
		subset: config?.subset ? [...config.subset] : null,
		keep: config?.keep || 'first'
	});

	const keepStrategies = [
		{ value: 'first', label: 'Keep First', description: 'Keep the first occurrence of each duplicate' },
		{
			value: 'last',
			label: 'Keep Last',
			description: 'Keep the last occurrence of each duplicate'
		},
		{ value: 'none', label: 'Keep None', description: 'Remove all duplicate rows' }
	];

	function toggleColumn(columnName: string) {
		if (!localConfig.subset) {
			localConfig.subset = [];
		}
		const index = localConfig.subset.indexOf(columnName);
		if (index > -1) {
			localConfig.subset.splice(index, 1);
		} else {
			localConfig.subset.push(columnName);
		}
	}

	function selectAllColumns() {
		localConfig.subset = schema.columns.map((c) => c.name);
	}

	function deselectAllColumns() {
		localConfig.subset = [];
	}

	function handleSave() {
		onSave({
			subset: localConfig.subset && localConfig.subset.length > 0 ? localConfig.subset : null,
			keep: localConfig.keep
		});
	}

	function handleCancel() {
		localConfig = {
			subset: config?.subset ? [...config.subset] : null,
			keep: config?.keep || 'first'
		};
	}
</script>

<div class="deduplicate-config">
	<h3>Deduplicate Configuration</h3>

	<div class="help-banner">
		Remove duplicate rows from your dataset. Choose which columns to check for duplicates, and
		which duplicate to keep.
	</div>

	<div class="section">
		<h4>Keep Strategy</h4>
		<div class="strategy-grid">
			{#each keepStrategies as strategy}
				<label class="strategy-option">
					<input type="radio" bind:group={localConfig.keep} value={strategy.value} />
					<div class="strategy-content">
						<div class="strategy-label">{strategy.label}</div>
						<div class="strategy-description">{strategy.description}</div>
					</div>
				</label>
			{/each}
		</div>
	</div>

	<div class="section">
		<h4>Column Subset</h4>
		<p class="help-text">
			Select specific columns to check for duplicates. If none selected, all columns will be
			checked.
		</p>

		<div class="column-actions">
			<button type="button" onclick={selectAllColumns} class="action-btn">Select All</button>
			<button type="button" onclick={deselectAllColumns} class="action-btn">Deselect All</button>
		</div>

		<div class="column-list">
			{#each schema.columns as column}
				<label class="column-item">
					<input
						type="checkbox"
						checked={localConfig.subset?.includes(column.name) || false}
						onchange={() => toggleColumn(column.name)}
					/>
					<span>{column.name} ({column.dtype})</span>
				</label>
			{/each}
		</div>

		{#if localConfig.subset && localConfig.subset.length > 0}
			<div class="selected-info">
				Checking {localConfig.subset.length} column{localConfig.subset.length !== 1 ? 's' : ''}:
				{localConfig.subset.join(', ')}
			</div>
		{:else}
			<div class="selected-info">No columns selected - will check all columns for duplicates</div>
		{/if}
	</div>

	<div class="example">
		<strong>Example:</strong> Remove duplicate emails by selecting only the "email" column and keeping
		the first occurrence.
	</div>

	<div class="actions">
		<button type="button" onclick={handleSave} class="save-btn">Save</button>
		<button type="button" onclick={handleCancel} class="cancel-btn">Cancel</button>
	</div>
</div>

<style>
	.deduplicate-config {
		padding: 1rem;
		border: 1px solid #ddd;
		border-radius: 4px;
	}

	h3 {
		margin-top: 0;
		margin-bottom: 1rem;
	}

	h4 {
		margin-top: 0;
		margin-bottom: 0.75rem;
		font-size: 1rem;
	}

	.help-banner {
		background-color: #e7f3ff;
		padding: 0.75rem;
		border-left: 3px solid #007bff;
		border-radius: 4px;
		margin-bottom: 1rem;
		font-size: 0.875rem;
	}

	.section {
		margin-bottom: 1.5rem;
		padding: 1rem;
		background-color: #f8f9fa;
		border-radius: 4px;
	}

	.help-text {
		font-size: 0.875rem;
		color: #6c757d;
		margin-bottom: 0.75rem;
	}

	.strategy-grid {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.strategy-option {
		display: flex;
		align-items: flex-start;
		gap: 0.75rem;
		padding: 0.75rem;
		background-color: white;
		border: 2px solid #ddd;
		border-radius: 4px;
		cursor: pointer;
		transition: all 0.2s;
	}

	.strategy-option:hover {
		border-color: #007bff;
		background-color: #f8f9ff;
	}

	.strategy-option input[type='radio'] {
		margin-top: 0.25rem;
		cursor: pointer;
	}

	.strategy-option input[type='radio']:checked + .strategy-content {
		color: #007bff;
	}

	.strategy-content {
		flex: 1;
	}

	.strategy-label {
		font-weight: 500;
		margin-bottom: 0.25rem;
	}

	.strategy-description {
		font-size: 0.875rem;
		color: #6c757d;
	}

	.column-actions {
		display: flex;
		gap: 0.5rem;
		margin-bottom: 0.75rem;
	}

	.action-btn {
		padding: 0.25rem 0.75rem;
		background-color: #6c757d;
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
		font-size: 0.875rem;
	}

	.action-btn:hover {
		opacity: 0.9;
	}

	.column-list {
		max-height: 200px;
		overflow-y: auto;
		border: 1px solid #ddd;
		border-radius: 4px;
		padding: 0.5rem;
		background-color: white;
	}

	.column-item {
		display: flex;
		align-items: center;
		padding: 0.5rem;
		cursor: pointer;
		border-radius: 4px;
	}

	.column-item:hover {
		background-color: #f8f9fa;
	}

	.column-item input[type='checkbox'] {
		margin-right: 0.5rem;
		cursor: pointer;
	}

	.selected-info {
		margin-top: 0.5rem;
		padding: 0.5rem;
		background-color: #e7f3ff;
		border-radius: 4px;
		font-size: 0.875rem;
	}

	.example {
		margin-bottom: 1rem;
		padding: 0.75rem;
		background-color: #fff3cd;
		border-left: 3px solid #ffc107;
		border-radius: 4px;
		font-size: 0.875rem;
	}

	.actions {
		display: flex;
		gap: 0.5rem;
	}

	.save-btn {
		padding: 0.5rem 1.5rem;
		background-color: #007bff;
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
	}

	.cancel-btn {
		padding: 0.5rem 1.5rem;
		background-color: #6c757d;
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
	}

	button:hover:not(:disabled) {
		opacity: 0.9;
	}
</style>
