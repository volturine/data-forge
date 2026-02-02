<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import type { Udf } from '$lib/types/udf';

	import { onClickOutside } from 'runed';
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { listUdfs, createUdf } from '$lib/api/udf';
	import CodeEditor from '$lib/components/common/CodeEditor.svelte';
	import UdfPickerModal from '$lib/components/udfs/UdfPickerModal.svelte';

	interface WithColumnsExpr {
		name: string;
		type: 'literal' | 'column' | 'udf';
		value?: string | number | null;
		column?: string | null;
		args?: string[] | null;
		code?: string | null;
		udf_id?: string | null;
	}

	interface WithColumnsConfigData {
		expressions: WithColumnsExpr[];
	}

	interface Props {
		schema: Schema;
		config?: WithColumnsConfigData;
	}

	let { schema, config = $bindable({ expressions: [] }) }: Props = $props();

	let exprType = $state<'column' | 'literal' | 'udf'>('column');
	let exprName = $state('');
	let exprColumn = $state('');
	let exprValue = $state('');
	let exprArgs = $state<string[]>([]);
	let exprCode = $state('');
	let exprUdfId = $state('');
	let useLibrary = $state(false);
	let showEditor = $state(false);
	let codeEdited = $state(false);
	let modalRef = $state<HTMLElement>();
	let columnRef = $state<HTMLElement>();
	let columnOpen = $state(false);
	let columnOrder = $derived(schema.columns.map((col) => col.name));
	let editIndex = $state<number | null>(null);
	let isEditing = $derived(editIndex !== null);
	let pickerOpen = $state(false);
	let saveToLibrary = $state(false);
	let saveName = $state('');
	let saveDescription = $state('');
	let saveTags = $state('');

	const queryClient = useQueryClient();

	const udfQuery = createQuery(() => ({
		queryKey: ['udfs'],
		queryFn: async () => {
			const result = await listUdfs();
			if (result.isErr()) {
				throw new Error(result.error.message);
			}
			return result.value;
		}
	}));

	const saveMutation = createMutation(() => ({
		mutationFn: async () => {
			const tagList = saveTags
				.split(',')
				.map((item) => item.trim())
				.filter(Boolean);
			const signature = {
				inputs: exprArgs.map((name, index) => {
					const column = schema.columns.find((col) => col.name === name);
					return { position: index, dtype: column?.dtype ?? 'Unknown', label: name };
				}),
				output_dtype: null
			};
			const result = await createUdf({
				name: saveName || exprName,
				description: saveDescription || null,
				signature,
				code: exprCode,
				tags: tagList.length ? tagList : null
			});
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		onSuccess: (udf: Udf) => {
			queryClient.invalidateQueries({ queryKey: ['udfs'] });
			exprUdfId = udf.id;
			useLibrary = true;
			saveToLibrary = false;
			saveName = '';
			saveDescription = '';
			saveTags = '';
		}
	}));

	let canAdd = $derived(
		!!exprName &&
			(exprType === 'column'
				? !!exprColumn
				: exprType === 'literal'
					? exprValue !== ''
					: useLibrary
						? !!exprUdfId && exprArgs.length > 0
						: !!exprCode)
	);

	function toArg(name: string): string {
		const safe = name.replace(/[^a-zA-Z0-9_]/g, '_');
		return `column_${safe}`;
	}

	function buildUdfCode(args: string[]): string {
		const params = args.map(toArg).join(', ');
		if (!params) return 'def udf():\n    return None\n';
		const first = params.split(', ')[0] ?? 'value';
		return `def udf(${params}):\n    # TODO: return a value\n    return ${first}\n`;
	}

	function sortArgs(args: string[]): string[] {
		return columnOrder.filter((name) => args.includes(name));
	}

	function toggleArg(name: string) {
		const exists = exprArgs.includes(name);
		const next = exists ? exprArgs.filter((item) => item !== name) : [...exprArgs, name];
		exprArgs = sortArgs(next);
	}

	function selectColumn(name: string) {
		exprColumn = name;
		columnOpen = false;
	}

	function dtypeClass(dtype: string): string {
		const value = dtype.toLowerCase();
		if (value.includes('string') || value.includes('utf') || value.includes('cat'))
			return 'dtype-string';
		if (value.includes('int') || value.includes('float') || value.includes('num'))
			return 'dtype-number';
		if (value.includes('date') || value.includes('time') || value.includes('duration'))
			return 'dtype-time';
		if (value.includes('bool')) return 'dtype-bool';
		return 'dtype-other';
	}

	$effect(() => {
		if (exprType !== 'udf') return;
		if (codeEdited) return;
		exprCode = buildUdfCode(exprArgs);
	});

	function openEditor() {
		showEditor = true;
		if (codeEdited) return;
		if (!exprCode) exprCode = buildUdfCode(exprArgs);
	}

	function buildExpression(): WithColumnsExpr {
		if (exprType === 'column') return { name: exprName, type: 'column', column: exprColumn };
		if (exprType === 'literal') return { name: exprName, type: 'literal', value: exprValue };
		if (useLibrary) {
			return { name: exprName, type: 'udf', udf_id: exprUdfId, args: exprArgs };
		}
		return { name: exprName, type: 'udf', code: exprCode, args: exprArgs };
	}

	function resetForm() {
		exprName = '';
		exprColumn = '';
		exprValue = '';
		exprArgs = [];
		exprCode = '';
		exprUdfId = '';
		useLibrary = false;
		codeEdited = false;
		exprType = 'column';
		editIndex = null;
		saveToLibrary = false;
		saveName = '';
		saveDescription = '';
		saveTags = '';
	}

	function addExpression() {
		if (!canAdd) return;
		const expressions = Array.isArray(config.expressions) ? config.expressions : [];
		config.expressions = [...expressions, buildExpression()];
		resetForm();
	}

	function saveExpression() {
		if (!canAdd || editIndex === null) return;
		const expressions = Array.isArray(config.expressions) ? [...config.expressions] : [];
		expressions[editIndex] = buildExpression();
		config.expressions = expressions;
		resetForm();
	}

	function editExpression(index: number) {
		const expr = config.expressions?.[index];
		if (!expr) return;
		exprType = expr.type;
		exprName = expr.name;
		exprColumn = expr.column ?? '';
		exprValue = String(expr.value ?? '');
		exprArgs = expr.args ?? [];
		exprCode = expr.code ?? '';
		exprUdfId = expr.udf_id ?? '';
		useLibrary = !!expr.udf_id;
		codeEdited = !!expr.code;
		editIndex = index;
	}

	function openPicker() {
		pickerOpen = true;
	}

	function handlePick(udf: Udf) {
		exprUdfId = udf.id;
		exprArgs = [];
		pickerOpen = false;
	}

	function cancelEdit() {
		resetForm();
	}

	function removeExpression(index: number) {
		const expressions = Array.isArray(config.expressions) ? config.expressions : [];
		config.expressions = expressions.filter((_: WithColumnsExpr, idx: number) => idx !== index);
		if (editIndex === index) resetForm();
	}

	onClickOutside(
		() => modalRef,
		() => {
			if (showEditor) showEditor = false;
		}
	);

	onClickOutside(
		() => columnRef,
		() => {
			if (!columnOpen) return;
			columnOpen = false;
		}
	);
</script>

<div class="config-panel" role="region" aria-label="With columns configuration">
	<h3>With Columns</h3>

	<div class="add-form">
		<select bind:value={exprType}>
			<option value="column">From column</option>
			<option value="literal">Literal value</option>
			<option value="udf">Python UDF</option>
		</select>

		<input type="text" bind:value={exprName} placeholder="New column name" />

		{#if exprType === 'column'}
			<div class="column-select" bind:this={columnRef}>
				<button
					type="button"
					class="column-trigger"
					onclick={() => (columnOpen = !columnOpen)}
					aria-expanded={columnOpen}
				>
					{#if exprColumn}
						{@const currentColumn = schema.columns.find((col) => col.name === exprColumn)}
						<span class={`column-type ${dtypeClass(currentColumn?.dtype ?? 'Unknown')}`}>
							{currentColumn?.dtype ?? 'Unknown'}
						</span>
						<span class="column-label">{exprColumn}</span>
					{:else}
						<span class="column-placeholder">Select source column...</span>
					{/if}
					<span class="chevron">▾</span>
				</button>
				{#if columnOpen}
					<div class="column-menu" role="listbox">
						<div class="column-options">
							{#each schema.columns as column (column.name)}
								<button
									type="button"
									class="column-option"
									class:selected={exprColumn === column.name}
									onclick={() => selectColumn(column.name)}
									role="option"
									aria-selected={exprColumn === column.name}
								>
									<span>{column.name}</span>
									<span class={`column-type ${dtypeClass(column.dtype)}`}>{column.dtype}</span>
								</button>
							{/each}
						</div>
					</div>
				{/if}
			</div>
		{:else if exprType === 'literal'}
			<input type="text" bind:value={exprValue} placeholder="Literal value" />
		{:else}
			<div class="udf-section">
				<div class="mode-toggle">
					<label class="toggle">
						<input type="radio" bind:group={useLibrary} value={false} />
						Inline UDF
					</label>
					<label class="toggle">
						<input type="radio" bind:group={useLibrary} value={true} />
						Library UDF
					</label>
				</div>

				{#if useLibrary}
					<div class="library-picker">
						<button type="button" class="btn-secondary btn-sm" onclick={openPicker}>
							Select UDF
						</button>
						{#if exprUdfId}
							{@const selectedUdf = (udfQuery.data ?? []).find((item) => item.id === exprUdfId)}
							<span class="selected">Selected: {selectedUdf?.name ?? exprUdfId}</span>
						{:else}
							<span class="selected">No UDF selected</span>
						{/if}
					</div>
					<span class="section-label">Input columns</span>
					<div class="column-grid">
						{#each schema.columns as column (column.name)}
							<label class="column-option">
								<input
									type="checkbox"
									checked={exprArgs.includes(column.name)}
									onchange={() => toggleArg(column.name)}
								/>
								<span>{column.name}</span>
								<span class={`column-type ${dtypeClass(column.dtype)}`}>{column.dtype}</span>
							</label>
						{/each}
					</div>
				{:else}
					<span class="section-label">Input columns</span>
					<div class="column-grid">
						{#each schema.columns as column (column.name)}
							<label class="column-option">
								<input
									type="checkbox"
									checked={exprArgs.includes(column.name)}
									onchange={() => toggleArg(column.name)}
								/>
								<span>{column.name}</span>
								<span class={`column-type ${dtypeClass(column.dtype)}`}>{column.dtype}</span>
							</label>
						{/each}
					</div>

					<div class="code-header">
						<span class="section-label">Function</span>
						<button type="button" class="btn-ghost btn-sm" onclick={openEditor}>Expand</button>
					</div>
					<textarea
						class="code-input"
						rows="5"
						placeholder="def udf(*args):&#10;    return ..."
						bind:value={exprCode}
						oninput={() => (codeEdited = true)}
					></textarea>
					<label class="toggle save-toggle">
						<input type="checkbox" bind:checked={saveToLibrary} />
						Save to UDF Library
					</label>
					{#if saveToLibrary}
						<div class="save-fields">
							<input type="text" placeholder="UDF name" bind:value={saveName} />
							<input type="text" placeholder="Description" bind:value={saveDescription} />
							<input type="text" placeholder="Tags (comma-separated)" bind:value={saveTags} />
							<button
								type="button"
								class="btn-secondary btn-sm"
								onclick={() => saveMutation.mutate()}
								disabled={!exprCode.trim()}
							>
								Save to Library
							</button>
						</div>
					{/if}
				{/if}
			</div>
		{/if}

		<div class="form-actions">
			{#if isEditing}
				<button type="button" class="btn-primary" onclick={saveExpression} disabled={!canAdd}
					>Save</button
				>
				<button type="button" class="btn-secondary" onclick={cancelEdit}>Cancel</button>
			{:else}
				<button type="button" class="btn-primary" onclick={addExpression} disabled={!canAdd}
					>Add</button
				>
			{/if}
		</div>
	</div>

	{#if (config.expressions ?? []).length > 0}
		<div class="items-list" role="list">
			<h4>Columns</h4>
			{#each config.expressions ?? [] as expr, index (index)}
				<div class="item" class:editing={editIndex === index} role="listitem">
					<div class="item-info">
						<span class="item-name" title={expr.name}>{expr.name}</span>
						<span class="item-meta">
							{expr.type === 'column'
								? `← ${expr.column ?? ''}`
								: expr.type === 'udf'
									? `udf(${(expr.args ?? []).length} args${expr.udf_id ? ', library' : ''})`
									: `= "${expr.value}"`}
						</span>
					</div>
					<div class="item-actions">
						<button
							type="button"
							class="btn-edit"
							onclick={() => editExpression(index)}
							aria-label="Edit"
						>
							<svg
								width="14"
								height="14"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
							>
								<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
								<path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
							</svg>
						</button>
						<button
							type="button"
							class="btn-remove"
							onclick={() => removeExpression(index)}
							aria-label="Remove">×</button
						>
					</div>
				</div>
			{/each}
		</div>
	{:else}
		<p class="empty-state">No columns configured yet.</p>
	{/if}
</div>

{#if showEditor}
	<div class="modal-backdrop" aria-hidden="true"></div>
	<div class="modal" role="dialog" aria-modal="true" bind:this={modalRef}>
		<div class="modal-header">
			<h2>UDF Editor</h2>
			<button class="modal-close" onclick={() => (showEditor = false)} aria-label="Close">×</button>
		</div>
		<div class="modal-body">
			<CodeEditor bind:value={exprCode} height="400px" onEdit={() => (codeEdited = true)} />
			<p class="help-text">
				Define a function named <code>udf</code> that returns a value per row.
			</p>
		</div>
		<div class="modal-footer">
			<button class="btn-secondary" onclick={() => (showEditor = false)} type="button">Done</button>
		</div>
	</div>
{/if}

<UdfPickerModal
	show={pickerOpen}
	udfs={udfQuery.data ?? []}
	onSelect={handlePick}
	onClose={() => (pickerOpen = false)}
/>

<style>
	h3 {
		margin: 0 0 var(--space-4) 0;
		font-size: var(--text-sm);
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--fg-muted);
	}
	h4 {
		margin: 0 0 var(--space-3) 0;
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--fg-muted);
	}

	.add-form {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		margin-bottom: var(--space-5);
	}
	.form-actions {
		display: flex;
		gap: var(--space-2);
	}

	.udf-section {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.section-label {
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--fg-muted);
	}
	.column-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
		gap: var(--space-2);
		padding: var(--space-3);
		background-color: var(--bg-primary);
		border: 1px solid var(--border-secondary);
		border-radius: var(--radius-sm);
		max-height: 160px;
		overflow-y: auto;
	}
	.column-legend {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin-bottom: var(--space-2);
	}
	.badge {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 2px 6px;
		border-radius: var(--radius-sm);
		border: 1px solid var(--border-primary);
		font-size: var(--text-xs);
		color: var(--fg-secondary);
		background-color: var(--bg-primary);
	}
	.dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		display: inline-block;
	}
	.dot-string {
		background-color: #7dd3fc;
	}
	.dot-number {
		background-color: #fbbf24;
	}
	.dot-time {
		background-color: #34d399;
	}
	.dot-bool {
		background-color: #f472b6;
	}
	.dot-other {
		background-color: #a3a3a3;
	}
	.column-option {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-sm);
		color: var(--fg-primary);
		cursor: pointer;
	}
	.column-option.selected {
		background-color: var(--bg-hover);
		border-radius: var(--radius-sm);
		padding: 2px 4px;
	}
	.column-type {
		font-size: var(--text-xs);
		color: var(--fg-muted);
		margin-left: auto;
		border-radius: 999px;
		padding: 2px 6px;
		background-color: var(--bg-secondary);
	}
	.column-type.dtype-string {
		color: #7dd3fc;
		border: 1px solid color-mix(in srgb, #7dd3fc 40%, transparent);
	}
	.column-type.dtype-number {
		color: #fbbf24;
		border: 1px solid color-mix(in srgb, #fbbf24 40%, transparent);
	}
	.column-type.dtype-time {
		color: #34d399;
		border: 1px solid color-mix(in srgb, #34d399 40%, transparent);
	}
	.column-type.dtype-bool {
		color: #f472b6;
		border: 1px solid color-mix(in srgb, #f472b6 40%, transparent);
	}
	.column-type.dtype-other {
		color: #a3a3a3;
		border: 1px solid color-mix(in srgb, #a3a3a3 40%, transparent);
	}
	.column-option input {
		width: auto;
	}
	.column-select {
		position: relative;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.column-trigger {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-sm);
		border: 1px solid var(--border-secondary);
		background-color: var(--bg-secondary);
		color: var(--fg-primary);
		cursor: pointer;
		justify-content: space-between;
		font-size: var(--text-sm);
	}
	.column-trigger:focus-visible {
		outline: 2px solid var(--accent-primary);
		outline-offset: 2px;
	}
	.column-placeholder {
		color: var(--fg-muted);
	}
	.column-label {
		flex: 1;
		text-align: left;
	}
	.column-trigger .column-type {
		margin-left: 0;
	}
	.chevron {
		font-size: 0.75rem;
		color: var(--fg-muted);
	}
	.column-menu {
		position: absolute;
		z-index: 10;
		top: calc(100% + 6px);
		left: 0;
		right: 0;
		background-color: var(--panel-bg);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		box-shadow: var(--dialog-shadow);
		padding: var(--space-2);
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.column-options {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		max-height: 220px;
		overflow-y: auto;
		padding-right: var(--space-1);
	}
	.column-options .column-option {
		width: 100%;
		padding: var(--space-2);
		border: 1px solid transparent;
		border-radius: var(--radius-sm);
		background: transparent;
		justify-content: space-between;
		text-align: left;
	}
	.column-options .column-option:hover {
		background-color: var(--bg-hover);
		border-color: var(--border-secondary);
	}
	.column-options .column-option.selected {
		background-color: var(--bg-hover);
		border-color: var(--border-secondary);
	}
	.code-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}
	.code-input {
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		resize: vertical;
		min-height: 100px;
	}

	.items-list {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding: var(--space-3);
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-md);
		border: 1px solid var(--border-primary);
	}
	.item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--space-2) var(--space-3);
		background-color: var(--bg-primary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
	}
	.item-info {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		min-width: 0;
	}
	.item-name {
		font-weight: 600;
		color: var(--fg-primary);
		max-width: 120px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.item-meta {
		font-size: var(--text-xs);
		color: var(--fg-muted);
	}
	.item.editing {
		border-color: var(--accent-primary);
		background-color: var(--bg-hover);
	}
	.item-actions {
		display: flex;
		gap: var(--space-1);
		flex-shrink: 0;
	}
	.item-actions button {
		width: 24px;
		height: 24px;
		padding: 0;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		background-color: transparent;
		color: var(--fg-muted);
		border: 1px solid transparent;
		border-radius: var(--radius-sm);
		cursor: pointer;
		font-size: 1rem;
		line-height: 1;
	}
	.item-actions button svg {
		width: 14px;
		height: 14px;
		flex-shrink: 0;
	}
	.item-actions button:hover {
		color: var(--fg-primary);
		background-color: var(--bg-tertiary);
		border-color: var(--border-primary);
	}
	.btn-remove:hover {
		color: var(--error-fg);
		background-color: var(--error-bg);
		border-color: var(--error-border);
	}

	.empty-state {
		padding: var(--space-6);
		text-align: center;
		color: var(--fg-muted);
		background-color: var(--bg-tertiary);
		border-radius: var(--radius-md);
		border: 1px dashed var(--border-primary);
	}
	.mode-toggle {
		display: flex;
		gap: var(--space-3);
		align-items: center;
	}
	.toggle {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-sm);
		color: var(--fg-secondary);
	}
	.library-picker {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.selected {
		font-size: var(--text-xs);
		color: var(--fg-muted);
	}
	.save-toggle {
		margin-top: var(--space-2);
	}
	.save-fields {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding: var(--space-3);
		background-color: var(--bg-tertiary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
	}

	.modal-backdrop {
		position: fixed;
		inset: 0;
		background: var(--overlay-bg);
		z-index: var(--z-modal);
	}
	.modal {
		position: fixed;
		left: 50%;
		top: 50%;
		transform: translate(-50%, -50%);
		width: min(720px, 90vw);
		background-color: var(--dialog-bg);
		border: 1px solid var(--dialog-border);
		border-radius: var(--radius-lg);
		box-shadow: var(--dialog-shadow);
		z-index: calc(var(--z-modal) + 1);
		display: flex;
		flex-direction: column;
	}
	.modal-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--space-3) var(--space-4);
		border-bottom: 1px solid var(--border-primary);
	}
	.modal-header h2 {
		margin: 0;
		font-size: var(--text-base);
		color: var(--fg-primary);
	}
	.modal-close {
		background: transparent;
		border: none;
		color: var(--fg-muted);
		cursor: pointer;
		font-size: 1.25rem;
		padding: 0;
	}
	.modal-close:hover {
		color: var(--fg-primary);
	}
	.modal-body {
		padding: var(--space-4);
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.modal-footer {
		padding: var(--space-3) var(--space-4);
		border-top: 1px solid var(--border-primary);
		display: flex;
		justify-content: flex-end;
	}
	.help-text {
		font-size: var(--text-sm);
		color: var(--fg-muted);
		margin: 0;
	}
</style>
