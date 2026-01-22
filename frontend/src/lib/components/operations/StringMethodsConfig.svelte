<script lang="ts">
	import type { Schema } from '$lib/types/schema';

	interface StringMethodsConfigData {
		column: string;
		method: string;
		new_column: string;
		start?: number;
		end?: number | null;
		pattern?: string;
		replacement?: string;
		group_index?: number;
		delimiter?: string;
		index?: number;
	}

	interface Props {
		schema: Schema;
		config?: StringMethodsConfigData;
	}

	let {
		schema,
		config = $bindable({
			column: '',
			method: 'uppercase',
			new_column: '',
			start: 0,
			end: null,
			pattern: '',
			replacement: '',
			group_index: 0,
			delimiter: ' ',
			index: 0
		})
	}: Props = $props();

	const methods = [
		{ value: 'uppercase', label: 'Uppercase', params: [] },
		{ value: 'lowercase', label: 'Lowercase', params: [] },
		{ value: 'title', label: 'Title Case', params: [] },
		{ value: 'strip', label: 'Strip (Trim)', params: [] },
		{ value: 'lstrip', label: 'Left Strip', params: [] },
		{ value: 'rstrip', label: 'Right Strip', params: [] },
		{ value: 'length', label: 'String Length', params: [] },
		{ value: 'slice', label: 'Substring (Slice)', params: ['start', 'end'] },
		{ value: 'replace', label: 'Replace Text', params: ['pattern', 'replacement'] },
		{ value: 'extract', label: 'Extract (Regex)', params: ['pattern', 'group_index'] },
		{ value: 'split', label: 'Split String', params: ['delimiter', 'index'] }
	];

	const stringColumns = $derived(
		schema.columns.filter(
			(col) =>
				col.dtype.toLowerCase().includes('str') ||
				col.dtype.toLowerCase().includes('string') ||
				col.dtype.toLowerCase() === 'utf8'
		)
	);

	const currentMethod = $derived(methods.find((m) => m.value === config.method));

	function needsParam(param: string): boolean {
		return currentMethod?.params.includes(param) || false;
	}
</script>

<div class="string-methods-config">
	<h3>String Methods Configuration</h3>

	<div class="section">
		<h4>Source Column</h4>
		<select id="str-column" bind:value={config.column}>
			<option value="">Select string column...</option>
			{#each stringColumns as column (column.name)}
				<option value={column.name}>{column.name} ({column.dtype})</option>
			{/each}
		</select>
		{#if stringColumns.length === 0}
			<p class="warning">No string columns detected in schema</p>
		{/if}
	</div>

	<div class="section">
		<h4>String Method</h4>
		<select id="str-method" bind:value={config.method}>
			{#each methods as method (method.value)}
				<option value={method.value}>{method.label}</option>
			{/each}
		</select>
	</div>

	{#if needsParam('start') || needsParam('end')}
		<div class="section">
			<h4>Slice Parameters</h4>
			<div class="inline-group">
				<div class="input-group">
					<label for="start-index">Start Index:</label>
					<input id="start-index" type="number" bind:value={config.start} />
				</div>
				<div class="input-group">
					<label for="end-index">End Index (optional):</label>
					<input
						id="end-index"
						type="number"
						bind:value={config.end}
						placeholder="Leave empty for end"
					/>
				</div>
			</div>
		</div>
	{/if}

	{#if needsParam('pattern') && needsParam('replacement')}
		<div class="section">
			<h4>Replace Parameters</h4>
			<div class="input-group">
				<label for="replace-pattern">Pattern to find:</label>
				<input
					id="replace-pattern"
					type="text"
					bind:value={config.pattern}
					placeholder="Text or regex pattern"
				/>
			</div>
			<div class="input-group">
				<label for="replacement">Replacement:</label>
				<input
					id="replacement"
					type="text"
					bind:value={config.replacement}
					placeholder="Replacement text"
				/>
			</div>
		</div>
	{/if}

	{#if needsParam('pattern') && needsParam('group_index')}
		<div class="section">
			<h4>Extract Parameters</h4>
			<div class="input-group">
				<label for="extract-pattern">Regex Pattern:</label>
				<input
					id="extract-pattern"
					type="text"
					bind:value={config.pattern}
					placeholder="e.g., @(.+)$ to extract domain"
				/>
			</div>
			<div class="input-group">
				<label for="group-index">Group Index:</label>
				<input id="group-index" type="number" bind:value={config.group_index} min="0" />
			</div>
		</div>
	{/if}

	{#if needsParam('delimiter') && needsParam('index')}
		<div class="section">
			<h4>Split Parameters</h4>
			<div class="input-group">
				<label for="delimiter">Delimiter:</label>
				<input
					id="delimiter"
					type="text"
					bind:value={config.delimiter}
					placeholder="e.g., space, comma"
				/>
			</div>
			<div class="input-group">
				<label for="part-index">Part Index:</label>
				<input id="part-index" type="number" bind:value={config.index} min="0" />
			</div>
		</div>
	{/if}

	<div class="section">
		<h4>New Column Name</h4>
		<input
			id="str-new-column"
			type="text"
			bind:value={config.new_column}
			placeholder="e.g., name_upper, domain, first_name"
		/>
	</div>
</div>

<style>
	.string-methods-config {
		padding: 1rem;
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-md);
		background-color: var(--panel-bg);
	}

	h3 {
		margin-top: 0;
		margin-bottom: 1rem;
		color: var(--panel-header-fg);
	}

	h4 {
		margin-top: 0;
		margin-bottom: 0.5rem;
		font-size: 1rem;
		color: var(--fg-secondary);
	}

	.section {
		margin-bottom: 1.5rem;
		padding: 1rem;
		background-color: var(--form-section-bg);
		border-radius: var(--radius-md);
		border: 1px solid var(--form-section-border);
	}

	.warning {
		font-size: 0.875rem;
		color: var(--error-fg);
		margin-top: 0.5rem;
		margin-bottom: 0;
	}

	select,
	input[type='text'],
	input[type='number'] {
		width: 100%;
		padding: 0.5rem;
		border: 1px solid var(--form-control-border);
		border-radius: var(--radius-sm);
		background-color: var(--form-control-bg);
		color: var(--fg-primary);
	}

	.inline-group {
		display: flex;
		gap: 1rem;
	}

	.input-group {
		flex: 1;
	}

	.input-group label {
		display: block;
		font-size: 0.875rem;
		font-weight: 500;
		margin-bottom: 0.25rem;
		color: var(--fg-secondary);
	}
</style>
