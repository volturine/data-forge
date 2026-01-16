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
		config: StringMethodsConfigData;
		onSave: (config: StringMethodsConfigData) => void;
	}

	let { schema, config, onSave }: Props = $props();

	let localConfig = $state<StringMethodsConfigData>({
		column: config?.column || '',
		method: config?.method || 'uppercase',
		new_column: config?.new_column || '',
		start: config?.start || 0,
		end: config?.end || null,
		pattern: config?.pattern || '',
		replacement: config?.replacement || '',
		group_index: config?.group_index || 0,
		delimiter: config?.delimiter || ' ',
		index: config?.index || 0
	});

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

	const currentMethod = $derived(methods.find((m) => m.value === localConfig.method));

	function needsParam(param: string): boolean {
		return currentMethod?.params.includes(param) || false;
	}

	function handleSave() {
		const saveConfig: StringMethodsConfigData = {
			column: localConfig.column,
			method: localConfig.method,
			new_column: localConfig.new_column
		};

		if (needsParam('start')) saveConfig.start = localConfig.start;
		if (needsParam('end')) saveConfig.end = localConfig.end;
		if (needsParam('pattern')) saveConfig.pattern = localConfig.pattern;
		if (needsParam('replacement')) saveConfig.replacement = localConfig.replacement;
		if (needsParam('group_index')) saveConfig.group_index = localConfig.group_index;
		if (needsParam('delimiter')) saveConfig.delimiter = localConfig.delimiter;
		if (needsParam('index')) saveConfig.index = localConfig.index;

		onSave(saveConfig);
	}

	function handleCancel() {
		localConfig = {
			column: config?.column || '',
			method: config?.method || 'uppercase',
			new_column: config?.new_column || '',
			start: config?.start || 0,
			end: config?.end || null,
			pattern: config?.pattern || '',
			replacement: config?.replacement || '',
			group_index: config?.group_index || 0,
			delimiter: config?.delimiter || ' ',
			index: config?.index || 0
		};
	}
</script>

<div class="string-methods-config">
	<h3>String Methods Configuration</h3>

	<div class="section">
		<h4>Source Column</h4>
		<select bind:value={localConfig.column}>
			<option value="">Select string column...</option>
			{#each stringColumns as column}
				<option value={column.name}>{column.name} ({column.dtype})</option>
			{/each}
		</select>
		{#if stringColumns.length === 0}
			<p class="warning">No string columns detected in schema</p>
		{/if}
	</div>

	<div class="section">
		<h4>String Method</h4>
		<select bind:value={localConfig.method}>
			{#each methods as method}
				<option value={method.value}>{method.label}</option>
			{/each}
		</select>
	</div>

	{#if needsParam('start') || needsParam('end')}
		<div class="section">
			<h4>Slice Parameters</h4>
			<div class="inline-group">
				<div class="input-group">
					<label>Start Index:</label>
					<input type="number" bind:value={localConfig.start} />
				</div>
				<div class="input-group">
					<label>End Index (optional):</label>
					<input type="number" bind:value={localConfig.end} placeholder="Leave empty for end" />
				</div>
			</div>
			<p class="help-text">Extract substring from start to end index</p>
		</div>
	{/if}

	{#if needsParam('pattern') && needsParam('replacement')}
		<div class="section">
			<h4>Replace Parameters</h4>
			<div class="input-group">
				<label>Pattern to find:</label>
				<input type="text" bind:value={localConfig.pattern} placeholder="Text or regex pattern" />
			</div>
			<div class="input-group">
				<label>Replacement:</label>
				<input type="text" bind:value={localConfig.replacement} placeholder="Replacement text" />
			</div>
			<p class="help-text">Replace all occurrences of pattern with replacement</p>
		</div>
	{/if}

	{#if needsParam('pattern') && needsParam('group_index')}
		<div class="section">
			<h4>Extract Parameters</h4>
			<div class="input-group">
				<label>Regex Pattern:</label>
				<input
					type="text"
					bind:value={localConfig.pattern}
					placeholder="e.g., @(.+)$ to extract domain"
				/>
			</div>
			<div class="input-group">
				<label>Group Index:</label>
				<input type="number" bind:value={localConfig.group_index} min="0" />
			</div>
			<p class="help-text">Extract text matching regex group (0 = full match, 1+ = capture groups)</p>
		</div>
	{/if}

	{#if needsParam('delimiter') && needsParam('index')}
		<div class="section">
			<h4>Split Parameters</h4>
			<div class="input-group">
				<label>Delimiter:</label>
				<input type="text" bind:value={localConfig.delimiter} placeholder="e.g., space, comma" />
			</div>
			<div class="input-group">
				<label>Part Index:</label>
				<input type="number" bind:value={localConfig.index} min="0" />
			</div>
			<p class="help-text">Split by delimiter and keep part at index (0 = first part)</p>
		</div>
	{/if}

	<div class="section">
		<h4>New Column Name</h4>
		<input
			type="text"
			bind:value={localConfig.new_column}
			placeholder="e.g., name_upper, domain, first_name"
		/>
		<p class="help-text">Leave empty to overwrite source column</p>
	</div>

	<div class="actions">
		<button type="button" onclick={handleSave} class="save-btn" disabled={!localConfig.column || !localConfig.new_column}>
			Save
		</button>
		<button type="button" onclick={handleCancel} class="cancel-btn">Cancel</button>
	</div>
</div>

<style>
	.string-methods-config {
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
		margin-bottom: 0.5rem;
		font-size: 1rem;
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
		margin-top: 0.5rem;
		margin-bottom: 0;
	}

	.warning {
		font-size: 0.875rem;
		color: #dc3545;
		margin-top: 0.5rem;
		margin-bottom: 0;
	}

	select,
	input[type='text'],
	input[type='number'] {
		width: 100%;
		padding: 0.5rem;
		border: 1px solid #ccc;
		border-radius: 4px;
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

	.save-btn:disabled {
		background-color: #ccc;
		cursor: not-allowed;
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
