<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import type { Udf } from '$lib/types/udf';

	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { listUdfs, createUdf } from '$lib/api/udf';
	import CodeEditor from '$lib/components/common/CodeEditor.svelte';
	import UdfPickerModal from '$lib/components/common/UdfPickerModal.svelte';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';
	import MultiSelectColumnDropdown from '$lib/components/common/MultiSelectColumnDropdown.svelte';
	import BaseModal from '$lib/components/ui/BaseModal.svelte';
	import SectionHeader from '$lib/components/ui/SectionHeader.svelte';
	import PanelHeader from '$lib/components/ui/PanelHeader.svelte';
	import PanelFooter from '$lib/components/ui/PanelFooter.svelte';
	import { Pencil, X } from 'lucide-svelte';
	import { css, button, emptyText, input, label, stepConfig } from '$lib/styles/panda';

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
		<select id="wc-expr-type" class={input()} bind:value={exprType}>
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
					<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
						<button
							type="button"
							class={button({ variant: 'secondary', size: 'sm' })}
							onclick={openPicker}
						>
							Select UDF
						</button>
						{#if exprUdfId}
							{@const selectedUdf = (udfQuery.data ?? []).find((item) => item.id === exprUdfId)}
							<span class={label()}>Selected: {selectedUdf?.name ?? exprUdfId}</span>
						{:else}
							<span class={label()}>No UDF selected</span>
						{/if}
					</div>
					<span class={label()}>Input columns</span>
					<MultiSelectColumnDropdown
						{schema}
						value={exprArgs}
						onChange={(val) => (exprArgs = val)}
						placeholder="Select input columns..."
					/>
				{:else}
					<span class={label()}>Input columns</span>
					<MultiSelectColumnDropdown
						{schema}
						value={exprArgs}
						onChange={(val) => (exprArgs = val)}
						placeholder="Select input columns..."
					/>

					<div
						class={css({ display: 'flex', alignItems: 'center', justifyContent: 'space-between' })}
					>
						<label for="wc-expr-code" class={label()}>Function</label>
						<button
							type="button"
							class={button({ variant: 'ghost', size: 'sm' })}
							onclick={openEditor}>Expand</button
						>
					</div>
					<textarea
						id="wc-expr-code"
						class={css({
							width: 'full',
							color: 'fg.primary',
							backgroundColor: 'bg.primary',
							borderWidth: '1',
							borderRadius: '0',
							paddingX: '3.5',
							paddingY: '2.25',
							transitionProperty: 'border-color',
							transitionDuration: '160ms',
							transitionTimingFunction: 'ease',
							_focus: { outline: 'none' },
							_focusVisible: { borderColor: 'border.accent' },
							_disabled: { opacity: '0.5', cursor: 'not-allowed', backgroundColor: 'bg.tertiary' },
							_placeholder: { color: 'fg.muted' },
							resize: 'vertical',
							minHeight: 'fieldSm',
							fontSize: 'sm'
						})}
						rows="5"
						placeholder="def udf(*args):&#10;    return ..."
						bind:value={exprCode}
						oninput={() => (codeEdited = true)}
					></textarea>
					<label
						class={css({
							display: 'inline-flex',
							alignItems: 'center',
							gap: '2',
							fontSize: 'sm',
							fontWeight: 'normal',
							color: 'fg.secondary',
							textTransform: 'none',
							letterSpacing: 'normal',
							marginBottom: '0',
							marginTop: '2'
						})}
					>
						<input id="wc-save-to-lib" type="checkbox" bind:checked={saveToLibrary} />
						Save to UDF Library
					</label>
					{#if saveToLibrary}
						<div
							class={css({
								borderTopWidth: '1',
								display: 'flex',
								flexDirection: 'column',
								gap: '3',
								marginTop: '3',
								paddingTop: '3'
							})}
						>
							<label class={label()} for="wc-save-name">Name</label>
							<input
								id="wc-save-name"
								type="text"
								class={input()}
								placeholder="UDF name"
								bind:value={saveName}
							/>
							<label class={label()} for="wc-save-desc">Description</label>
							<input
								id="wc-save-desc"
								type="text"
								class={input()}
								placeholder="Description"
								bind:value={saveDescription}
							/>
							<label class={label()} for="wc-save-tags">Tags</label>
							<input
								id="wc-save-tags"
								type="text"
								class={input()}
								placeholder="Tags (comma-separated)"
								bind:value={saveTags}
							/>
							<button
								type="button"
								class={button({ variant: 'secondary', size: 'sm' })}
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

<BaseModal
	open={showEditor}
	onClose={() => (showEditor = false)}
	closeOnEscape={true}
	closeOnBackdrop={true}
	panelClass={css({
		width: 'min(720px, 92vw)',
		backgroundColor: 'bg.primary',
		borderWidth: '1',
		display: 'flex',
		flexDirection: 'column',
		_focus: { outline: 'none' }
	})}
	ariaLabelledby="wc-editor-title"
	{content}
/>

{#snippet content()}
	<PanelHeader>
		{#snippet title()}
			<span id="wc-editor-title">UDF Editor</span>
		{/snippet}
		{#snippet actions()}
			<button
				class={css({
					background: 'transparent',
					border: 'none',
					color: 'fg.muted',
					cursor: 'pointer',
					fontSize: 'xl',
					padding: '1',
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'center',
					transition: 'color 160ms ease, background-color 160ms ease',
					_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' }
				})}
				onclick={() => (showEditor = false)}
				aria-label="Close"
				type="button"
			>
				<X size={16} />
			</button>
		{/snippet}
	</PanelHeader>
	<div
		class={css({
			padding: '4',
			overflowY: 'auto',
			display: 'flex',
			flexDirection: 'column',
			gap: '3'
		})}
	>
		<CodeEditor bind:value={exprCode} height="400px" onEdit={() => (codeEdited = true)} />
		<p class={css({ fontSize: 'sm', margin: '0', color: 'fg.muted' })}>
			Define a function named <code>udf</code> that returns a value per row.
		</p>
	</div>
	<PanelFooter>
		<button
			class={button({ variant: 'secondary' })}
			onclick={() => (showEditor = false)}
			type="button">Done</button
		>
	</PanelFooter>
{/snippet}

<UdfPickerModal
	show={pickerOpen}
	udfs={udfQuery.data ?? []}
	onSelect={handlePick}
	onClose={() => (pickerOpen = false)}
/>
