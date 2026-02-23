<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import type { Udf } from '$lib/types/udf';

	import { onClickOutside } from 'runed';
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { listUdfs, createUdf } from '$lib/api/udf';
	import CodeEditor from '$lib/components/common/CodeEditor.svelte';
	import UdfPickerModal from '$lib/components/common/UdfPickerModal.svelte';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';
	import MultiSelectColumnDropdown from '$lib/components/common/MultiSelectColumnDropdown.svelte';
	import { Pencil, X } from 'lucide-svelte';

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
	let editIndex = $state<number | null>(null);
	const isEditing = $derived(editIndex !== null);
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
					return { position: index, dtype: column?.dtype ?? 'Any', label: name };
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

	const canAdd = $derived(
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
		return `def udf(${params}):\n    return ${first}\n`;
	}

	// Subscription: $derived can't sync editor code with args.
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
</script>

<div class="config-panel" role="region" aria-label="With columns configuration">
	<h3 class="m-0 mb-5 text-sm uppercase tracking-wider text-fg-muted">With Columns</h3>

	<div class="flex flex-col gap-3 mb-5">
		<select bind:value={exprType}>
			<option value="column">From column</option>
			<option value="literal">Literal value</option>
			<option value="udf">Python UDF</option>
		</select>

		<input type="text" bind:value={exprName} placeholder="New column name" />

		{#if exprType === 'column'}
			<ColumnDropdown
				{schema}
				value={exprColumn}
				onChange={(val) => (exprColumn = val)}
				placeholder="Select source column..."
			/>
		{:else if exprType === 'literal'}
			<input type="text" bind:value={exprValue} placeholder="Literal value" />
		{:else}
			<div class="flex flex-col gap-3">
				<div class="flex gap-3 items-center">
					<label class="inline-flex items-center gap-2 text-sm text-fg-secondary">
						<input type="radio" bind:group={useLibrary} value={false} />
						Inline UDF
					</label>
					<label class="inline-flex items-center gap-2 text-sm text-fg-secondary">
						<input type="radio" bind:group={useLibrary} value={true} />
						Library UDF
					</label>
				</div>

				{#if useLibrary}
					<div class="flex items-center gap-2">
						<button type="button" class="btn-secondary btn-sm" onclick={openPicker}>
							Select UDF
						</button>
						{#if exprUdfId}
							{@const selectedUdf = (udfQuery.data ?? []).find((item) => item.id === exprUdfId)}
							<span class="text-xs text-fg-muted">Selected: {selectedUdf?.name ?? exprUdfId}</span>
						{:else}
							<span class="text-xs text-fg-muted">No UDF selected</span>
						{/if}
					</div>
					<span class="text-xs uppercase tracking-wider text-fg-muted">Input columns</span>
					<MultiSelectColumnDropdown
						{schema}
						value={exprArgs}
						onChange={(val) => (exprArgs = val)}
						placeholder="Select input columns..."
					/>
				{:else}
					<span class="text-xs uppercase tracking-wider text-fg-muted">Input columns</span>
					<MultiSelectColumnDropdown
						{schema}
						value={exprArgs}
						onChange={(val) => (exprArgs = val)}
						placeholder="Select input columns..."
					/>

					<div class="flex items-center justify-between">
						<span class="text-xs uppercase tracking-wider text-fg-muted">Function</span>
						<button type="button" class="btn-ghost btn-sm" onclick={openEditor}>Expand</button>
					</div>
					<textarea
						class="resize-y min-h-25 text-sm font-mono"
						rows="5"
						placeholder="def udf(*args):&#10;    return ..."
						bind:value={exprCode}
						oninput={() => (codeEdited = true)}
					></textarea>
					<label class="inline-flex items-center gap-2 text-sm mt-2 text-fg-secondary">
						<input type="checkbox" bind:checked={saveToLibrary} />
						Save to UDF Library
					</label>
					{#if saveToLibrary}
						<div class="flex flex-col gap-3 mt-3 pt-3 border-t border-tertiary">
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

		<div class="flex gap-3">
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
		<div class="flex flex-col" role="list">
			<h4 class="m-0 mb-3">Columns</h4>
			{#each config.expressions ?? [] as expr, index (index)}
				<div
					class="item item-row flex justify-between items-center py-2"
					class:editing={editIndex === index}
					class:border-accent-primary={editIndex === index}
					class:bg-hover={editIndex === index}
					role="listitem"
				>
					<div class="flex items-center gap-3 min-w-0">
						<span
							class="font-semibold max-w-30 overflow-hidden text-ellipsis whitespace-nowrap text-fg-primary"
							title={expr.name}>{expr.name}</span
						>
						<span class="text-xs text-fg-muted">
							{expr.type === 'column'
								? `<- ${expr.column ?? ''}`
								: expr.type === 'udf'
									? `udf(${(expr.args ?? []).length} args${expr.udf_id ? ', library' : ''})`
									: `= "${expr.value}"`}
						</span>
					</div>
					<div class="flex gap-1 shrink-0">
						<button
							type="button"
							class="w-6 h-6 p-0 inline-flex items-center justify-center bg-transparent cursor-pointer text-base leading-none text-fg-muted border border-transparent"
							onclick={() => editExpression(index)}
							aria-label="Edit"
						>
							<Pencil size={14} />
						</button>
						<button
							type="button"
							class="btn-remove w-6 h-6 p-0 inline-flex items-center justify-center bg-transparent cursor-pointer text-base leading-none text-fg-muted border border-transparent hover:text-error-fg hover:bg-error hover:border-error"
							onclick={() => removeExpression(index)}
							aria-label="Remove"
						>
							<X size={14} />
						</button>
					</div>
				</div>
			{/each}
		</div>
	{:else}
		<p class="py-8 text-center text-xs text-fg-muted">No columns configured yet.</p>
	{/if}
</div>

{#if showEditor}
	<div class="modal-backdrop" aria-hidden="true"></div>
	<div class="modal" role="dialog" aria-modal="true" bind:this={modalRef}>
		<div class="modal-header">
			<h2>UDF Editor</h2>
			<button class="modal-close" onclick={() => (showEditor = false)} aria-label="Close">
				<X size={16} />
			</button>
		</div>
		<div class="modal-body">
			<CodeEditor bind:value={exprCode} height="400px" onEdit={() => (codeEdited = true)} />
			<p class="text-sm m-0 text-fg-muted">
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
