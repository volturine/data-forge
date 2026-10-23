<script lang="ts">
	import type { Schema } from '#lib/types/schema.js';
	import type { Udf, UdfCreate } from '#lib/types/udf.js';
	import type { WithColumnsConfigData, WithColumnsExpr } from '#lib/types/operation-config.js';

	import { createQuery } from '@tanstack/svelte-query';
	import { listUdfs } from '#lib/api/udf.js';
	import UdfPickerModal from '#lib/components/common/UdfPickerModal.svelte';
	import ColumnDropdown from '#lib/components/common/ColumnDropdown.svelte';
	import MultiSelectColumnDropdown from '#lib/components/common/MultiSelectColumnDropdown.svelte';
	import SectionHeader from '#lib/components/ui/SectionHeader.svelte';
	import { Pencil, X } from '@lucide/svelte';
	import { css, button, emptyText, input, label, stepConfig } from '#lib/styles/panda.js';

	interface Props {
		schema: Schema;
		config: WithColumnsConfigData;
	}

	let { schema, config = $bindable() }: Props = $props();

	let exprType = $state<'column' | 'literal' | 'udf'>('column');
	let exprName = $state('');
	let exprColumn = $state('');
	let exprValue = $state('');
	let exprArgs = $state<string[]>([]);
	let exprCode = $state('');
	let exprUdfId = $state('');
	let useLibrary = $state(false);
	let codeEdited = $state(false);
	let editIndex = $state<number | null>(null);
	const isEditing = $derived(editIndex !== null);
	let pickerOpen = $state(false);
	let editorUdf = $state<Udf | undefined>();
	let editorDraft = $state<UdfCreate | undefined>();
	let inlineDraft = $state<UdfCreate | undefined>();
	let inlineInputCount = $state<number | null>(null);

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

	const selectedUdf = $derived((udfQuery.data ?? []).find((udf) => udf.id === exprUdfId));

	const canAdd = $derived(
		!!exprName.trim() &&
			(exprType === 'column'
				? !!exprColumn
				: exprType === 'literal'
					? exprValue !== ''
					: useLibrary
						? !!selectedUdf && exprArgs.length === selectedUdf.signature.inputs.length
						: !!exprCode.trim() &&
							(inlineInputCount === null || exprArgs.length === inlineInputCount))
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

	function syncGeneratedCode(type = exprType, args = exprArgs): void {
		if (type !== 'udf') return;
		if (codeEdited) return;
		exprCode = buildUdfCode(args);
	}

	function setExprArgs(args: string[]): void {
		exprArgs = args;
		syncGeneratedCode(exprType, args);
	}

	function setExprType(event: Event): void {
		exprType = (event.currentTarget as HTMLSelectElement).value as 'column' | 'literal' | 'udf';
		syncGeneratedCode();
	}

	function openEditor(): void {
		if (useLibrary) {
			if (!selectedUdf) return;
			editorUdf = selectedUdf;
			editorDraft = undefined;
			pickerOpen = true;
			return;
		}
		const code = exprCode || buildUdfCode(exprArgs);
		editorUdf = undefined;
		editorDraft = {
			...inlineDraft,
			name: inlineDraft?.name ?? exprName,
			code,
			signature: inlineDraft?.signature ?? {
				inputs: exprArgs.map((name, position) => ({
					position,
					dtype: schema.columns.find((column) => column.name === name)?.dtype ?? 'Any',
					label: toArg(name)
				})),
				output_dtype: null
			}
		};
		pickerOpen = true;
	}

	function applyInlineUdf(draft: UdfCreate): void {
		inlineDraft = draft;
		exprCode = draft.code;
		inlineInputCount = draft.signature.inputs.length;
		if (exprArgs.length !== inlineInputCount) exprArgs = [];
		codeEdited = true;
		useLibrary = false;
		pickerOpen = false;
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
		inlineInputCount = null;
		editorUdf = undefined;
		editorDraft = undefined;
		inlineDraft = undefined;
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
		resetForm();
		exprType = expr.type;
		exprName = expr.name;
		exprColumn = expr.column ?? '';
		exprValue = String(expr.value ?? '');
		exprArgs = expr.args ?? [];
		exprCode = expr.code ?? '';
		exprUdfId = expr.udf_id ?? '';
		useLibrary = !!expr.udf_id;
		codeEdited = !!expr.code;
		if (expr.type === 'udf' && !useLibrary) inlineInputCount = exprArgs.length;
		editIndex = index;
	}

	function openPicker() {
		editorUdf = undefined;
		editorDraft = undefined;
		pickerOpen = true;
	}

	function handlePick(udf: Udf) {
		if (exprArgs.length !== udf.signature.inputs.length) exprArgs = [];
		exprUdfId = udf.id;
		exprCode = udf.code;
		inlineInputCount = udf.signature.inputs.length;
		inlineDraft = {
			name: udf.name,
			description: udf.description,
			tags: udf.tags,
			code: udf.code,
			signature: udf.signature
		};
		codeEdited = true;
		useLibrary = true;
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
</script>

<div class={stepConfig()} role="region" aria-label="With columns configuration">
	<h3
		class={css({
			margin: '0',
			marginBottom: '5',
			fontSize: 'sm',
			textTransform: 'uppercase',
			letterSpacing: 'wider',
			color: 'fg.muted'
		})}
	>
		With Columns
	</h3>

	<div class={css({ display: 'flex', flexDirection: 'column', gap: '3', marginBottom: '5' })}>
		<label class={label()} for="wc-expr-type">Type</label>
		<select id="wc-expr-type" class={input()} value={exprType} onchange={setExprType}>
			<option value="column">From column</option>
			<option value="literal">Literal value</option>
			<option value="udf">Python UDF</option>
		</select>

		<label class={label()} for="wc-expr-name">Column name</label>
		<input
			id="wc-expr-name"
			type="text"
			class={input()}
			bind:value={exprName}
			placeholder="New column name"
		/>

		{#if exprType === 'column'}
			<ColumnDropdown
				{schema}
				value={exprColumn}
				onChange={(val) => (exprColumn = val)}
				placeholder="Select source column..."
			/>
		{:else if exprType === 'literal'}
			<label class={label()} for="wc-expr-value">Value</label>
			<input
				id="wc-expr-value"
				type="text"
				class={input()}
				bind:value={exprValue}
				placeholder="Literal value"
			/>
		{:else}
			<div class={css({ display: 'flex', flexDirection: 'column', gap: '3' })}>
				<div class={css({ display: 'flex', alignItems: 'center', gap: '3' })}>
					<label class={label({ variant: 'inline' })}>
						<input id="wc-use-lib-no" type="radio" bind:group={useLibrary} value={false} />
						Inline UDF
					</label>
					<label class={label({ variant: 'inline' })}>
						<input id="wc-use-lib-yes" type="radio" bind:group={useLibrary} value={true} />
						Library UDF
					</label>
				</div>

				{#if useLibrary}
					<div class={css({ display: 'flex', alignItems: 'center', gap: '2', flexWrap: 'wrap' })}>
						<button
							type="button"
							class={button({ variant: 'secondary', size: 'sm' })}
							onclick={openPicker}>Select UDF</button
						>
						{#if selectedUdf}
							<button
								type="button"
								class={button({ variant: 'ghost', size: 'sm' })}
								onclick={openEditor}>Edit UDF</button
							>
							<span class={label()}>Selected: {selectedUdf.name}</span>
						{:else}
							<span class={label()}>No UDF selected</span>
						{/if}
					</div>
					{#if udfQuery.isError}
						<p role="alert" class={css({ color: 'fg.error', margin: '0' })}>
							{udfQuery.error.message}
						</p>
					{/if}
				{:else}
					<button
						type="button"
						class={button({ variant: 'secondary', size: 'sm' })}
						onclick={openEditor}>Edit UDF</button
					>
					<p class={css({ color: 'fg.muted', fontSize: 'xs', margin: '0' })}>
						Edit the function, inputs, and output type in the UDF editor. You can also save it to
						the library.
					</p>
				{/if}
				<span class={label()}>Input columns</span>
				<MultiSelectColumnDropdown
					{schema}
					value={exprArgs}
					onChange={setExprArgs}
					placeholder="Select input columns..."
				/>
				{#if useLibrary && selectedUdf}
					<p class={css({ color: 'fg.muted', fontSize: 'xs', margin: '0' })}>
						Select {selectedUdf.signature.inputs.length} input columns in function argument order.
					</p>
				{:else if inlineInputCount !== null}
					<p class={css({ color: 'fg.muted', fontSize: 'xs', margin: '0' })}>
						Select {inlineInputCount} input columns in function argument order.
					</p>
				{/if}
			</div>
		{/if}

		<div class={css({ display: 'flex', gap: '3' })}>
			{#if isEditing}
				<button
					type="button"
					class={button({ variant: 'primary' })}
					onclick={saveExpression}
					disabled={!canAdd}>Save</button
				>
				<button type="button" class={button({ variant: 'secondary' })} onclick={cancelEdit}
					>Cancel</button
				>
			{:else}
				<button
					type="button"
					class={button({ variant: 'primary' })}
					onclick={addExpression}
					disabled={!canAdd}>Add</button
				>
			{/if}
		</div>
	</div>

	{#if (config.expressions ?? []).length > 0}
		<div class={css({ display: 'flex', flexDirection: 'column' })} role="list">
			<SectionHeader>Columns</SectionHeader>
			{#each config.expressions ?? [] as expr, index (index)}
				<div
					class={editIndex === index
						? css({
								display: 'flex',
								justifyContent: 'space-between',
								alignItems: 'center',
								paddingY: '2',
								borderBottomWidth: '1',
								borderLeftWidth: '2',
								borderLeftColor: 'border.accent',
								backgroundColor: 'bg.hover',
								'&:last-child': { borderBottomWidth: '0' }
							})
						: css({
								display: 'flex',
								justifyContent: 'space-between',
								alignItems: 'center',
								paddingY: '2',
								borderBottomWidth: '1',
								backgroundColor: 'transparent',
								'&:last-child': { borderBottomWidth: '0' }
							})}
					role="listitem"
				>
					<div class={css({ display: 'flex', alignItems: 'center', gap: '3', minWidth: '0' })}>
						<span
							class={css({
								fontWeight: 'semibold',
								maxWidth: 'fieldMd',
								overflow: 'hidden',
								textOverflow: 'ellipsis',
								whiteSpace: 'nowrap'
							})}
							title={expr.name}>{expr.name}</span
						>
						<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>
							{expr.type === 'column'
								? `<- ${expr.column ?? ''}`
								: expr.type === 'udf'
									? `udf(${(expr.args ?? []).length} args${expr.udf_id ? ', library' : ''})`
									: `= "${expr.value}"`}
						</span>
					</div>
					<div class={css({ display: 'flex', gap: '1', flexShrink: '0' })}>
						<button
							type="button"
							class={css({
								width: 'iconLg',
								height: 'iconLg',
								padding: '0',
								display: 'inline-flex',
								alignItems: 'center',
								justifyContent: 'center',
								backgroundColor: 'transparent',
								cursor: 'pointer',
								fontSize: 'md',
								lineHeight: 'none',
								color: 'fg.muted',
								borderWidth: '1',
								borderColor: 'border.transparent'
							})}
							onclick={() => editExpression(index)}
							aria-label="Edit"
						>
							<Pencil size={14} />
						</button>
						<button
							type="button"
							class={css({
								width: 'iconLg',
								height: 'iconLg',
								padding: '0',
								display: 'inline-flex',
								alignItems: 'center',
								justifyContent: 'center',
								cursor: 'pointer',
								fontSize: 'md',
								lineHeight: 'none',
								borderWidth: '1',
								_hover: {
									color: 'fg.error',
									backgroundColor: 'bg.error',
									borderColor: 'border.error'
								}
							})}
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
		<p class={emptyText()}>No columns configured yet.</p>
	{/if}
</div>

{#if pickerOpen}
	<UdfPickerModal
		show={true}
		initialUdf={editorUdf}
		initialDraft={editorDraft}
		onSelect={handlePick}
		onApply={applyInlineUdf}
		onClose={() => (pickerOpen = false)}
	/>
{/if}
