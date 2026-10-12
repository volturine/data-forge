<script lang="ts">
	import { untrack } from 'svelte';
	import { useQueryClient } from '@tanstack/svelte-query';
	import { createUdf, updateUdf } from '$lib/api/udf';
	import CodeEditor from '$lib/components/common/CodeEditor.svelte';
	import ColumnTypeDropdown from '$lib/components/common/ColumnTypeDropdown.svelte';
	import UdfSignatureBuilder from '$lib/components/udfs/UdfSignatureBuilder.svelte';
	import type { Udf, UdfCreate, UdfInput, UdfSignature } from '$lib/types/udf';
	import { ArrowLeft, Save } from '@lucide/svelte';
	import { css, button, input, label } from '$lib/styles/panda';

	interface Props {
		initialUdf?: Udf;
		initialDraft?: UdfCreate;
		onSave: (udf: Udf) => void;
		onBack: () => void;
		onApply?: (draft: UdfCreate) => void;
		dirty?: boolean;
		saving?: boolean;
	}

	let {
		initialUdf,
		initialDraft,
		onSave,
		onBack,
		onApply,
		dirty = $bindable(false),
		saving = $bindable(false)
	}: Props = $props();
	const sourceUdf = untrack(() => initialUdf);
	const sourceDraft = untrack(() => initialDraft);
	const queryClient = useQueryClient();

	let name = $state(sourceUdf?.name ?? sourceDraft?.name ?? '');
	let description = $state(sourceUdf?.description ?? sourceDraft?.description ?? '');
	let tags = $state((sourceUdf?.tags ?? sourceDraft?.tags ?? []).join(', '));
	const initialInputs = sourceUdf?.signature.inputs ??
		sourceDraft?.signature.inputs ?? [{ position: 0, dtype: 'Float64', label: 'value' }];
	let inputs = $state.raw<UdfInput[]>(
		initialInputs.map((item) => ({
			...item
		}))
	);
	let outputDtype = $state(
		sourceUdf?.signature.output_dtype ?? sourceDraft?.signature.output_dtype ?? ''
	);
	let code = $state(sourceUdf?.code ?? sourceDraft?.code ?? 'def udf(value):\n    return value\n');
	let error = $state('');

	function toDraft(draftName = name): UdfCreate {
		const signature: UdfSignature = {
			inputs,
			output_dtype: outputDtype || null
		};
		const tagList = tags
			.split(',')
			.map((item) => item.trim())
			.filter(Boolean);
		return {
			name: draftName.trim(),
			description: description.trim() || null,
			signature,
			code,
			tags: tagList.length ? tagList : null
		};
	}

	function markDirty() {
		error = '';
		if (dirty) return;
		dirty = true;
	}

	function updateSignature(source: string, signature: string): string {
		return source.replace(/^(\s*)def udf\([^\n]*\)\s*:/m, `$1def udf(${signature}):`);
	}

	function updateInputs(next: UdfInput[]) {
		const previousLabels = inputs.map((item, index) => item.label?.trim() || `arg${index + 1}`);
		const nextLabels = next.map((item, index) => item.label?.trim() || `arg${index + 1}`);
		inputs = next;
		markDirty();
		if (
			previousLabels.length === nextLabels.length &&
			previousLabels.every((label, index) => label === nextLabels[index])
		)
			return;
		code = updateSignature(code, nextLabels.join(', '));
	}

	async function persist(asNew = false) {
		if (!canSave || saving) return;

		saving = true;
		error = '';
		const draft = toDraft(asNew && sourceUdf ? `${name} (copy)` : name);
		const result =
			sourceUdf && !asNew ? await updateUdf(sourceUdf.id, draft) : await createUdf(draft);
		if (result.isErr()) {
			error = result.error.message;
			saving = false;
			return;
		}

		const savedUdf = result.value;
		if (sourceUdf && !asNew) {
			queryClient.setQueriesData<Udf[]>({ queryKey: ['udfs'] }, (current) =>
				current?.map((udf) => (udf.id === savedUdf.id ? savedUdf : udf))
			);
		}
		await queryClient.invalidateQueries({ queryKey: ['udfs'] });
		dirty = false;
		saving = false;
		onSave(savedUdf);
	}

	function handleApply() {
		if (!onApply || !canApply || saving) return;
		dirty = false;
		onApply({ ...toDraft(), name: name.trim() });
	}

	function handleBack() {
		if (saving) return;
		onBack();
	}

	const canSave = $derived(name.trim().length > 0 && code.trim().length > 0);
	const canApply = $derived(code.trim().length > 0);
	const isEditing = $derived(!!sourceUdf);
</script>

<div class={css({ display: 'flex', minHeight: '0', flex: '1', flexDirection: 'column' })}>
	<header
		class={css({
			display: 'flex',
			flexDirection: 'column',
			justifyContent: 'space-between',
			alignItems: 'stretch',
			gap: '4',
			marginBottom: '5',
			padding: '5',
			borderBottomWidth: '1',
			sm: { flexDirection: 'row', alignItems: 'center' }
		})}
	>
		<div class={css({ display: 'flex', alignItems: 'center', gap: '3' })}>
			<button
				class={css({
					width: 'rowXl',
					height: 'rowXl',
					padding: '0',
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'center',
					backgroundColor: 'bg.tertiary',
					borderWidth: '1',
					color: 'fg.secondary',
					_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' },
					_disabled: { opacity: '0.5', cursor: 'not-allowed' }
				})}
				onclick={handleBack}
				type="button"
				aria-label="Back to UDF library"
				disabled={saving}
			>
				<ArrowLeft size={18} />
			</button>
			<div>
				<h3 class={css({ margin: '0', fontSize: 'lg' })}>Function definition</h3>
				<p class={css({ margin: '1 0 0', color: 'fg.tertiary', fontSize: 'sm' })}>
					{#if isEditing}
						Changes affect analyses that use this UDF. Save as new to preserve the original.
					{:else}
						Reusable Python transforms for your pipelines
					{/if}
				</p>
			</div>
		</div>
		<div class={css({ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '2' })}>
			{#if onApply}
				<button
					class={button({ variant: 'secondary' })}
					onclick={handleApply}
					disabled={!canApply || saving}
				>
					Use in analysis
				</button>
			{/if}
			{#if isEditing}
				<button
					class={button({ variant: 'secondary' })}
					data-testid="udf-save-as-new-button"
					onclick={() => persist(true)}
					disabled={!canSave || saving}
				>
					{saving ? 'Saving...' : 'Save as new'}
				</button>
			{/if}
			<button
				class={button({ variant: 'primary' })}
				data-testid="udf-save-button"
				onclick={() => persist()}
				disabled={!canSave || saving}
			>
				<Save size={16} />
				{saving ? 'Saving...' : 'Save UDF'}
			</button>
		</div>
	</header>
	{#if error}
		<div
			data-testid="udf-save-error"
			role="alert"
			class={css({
				marginX: '5',
				marginBottom: '3',
				paddingX: '3',
				paddingY: '2.5',
				borderLeftWidth: '2',
				fontSize: 'xs',
				lineHeight: 'normal',
				backgroundColor: 'transparent',
				borderLeftColor: 'border.error',
				color: 'fg.error'
			})}
		>
			{error}
		</div>
	{/if}

	<div
		class={css({ overflowY: 'auto', minHeight: '0', flex: '1', paddingX: '5', paddingBottom: '5' })}
	>
		<div class={css({ display: 'flex', flexDirection: 'column', gap: '5' })}>
			<div
				class={css({
					display: 'grid',
					gridTemplateColumns: '1fr',
					gap: '4',
					sm: { gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))' }
				})}
			>
				<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
					<label for="udf-name" class={label({ variant: 'field' })}>Name</label>
					<input
						id="udf-name"
						type="text"
						bind:value={name}
						oninput={markDirty}
						placeholder="UDF name"
						class={input()}
					/>
				</div>
				<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
					<label for="udf-description" class={label({ variant: 'field' })}>Description</label>
					<textarea
						id="udf-description"
						rows="3"
						bind:value={description}
						oninput={markDirty}
						class={input()}></textarea>
				</div>
				<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
					<label for="udf-tags" class={label({ variant: 'field' })}>Tags (comma-separated)</label>
					<input
						id="udf-tags"
						type="text"
						bind:value={tags}
						oninput={markDirty}
						placeholder="math, text, date"
						class={input()}
					/>
				</div>
			</div>

			<div
				class={css({
					display: 'flex',
					flexDirection: 'column',
					gap: '3',
					padding: '4',
					borderWidth: '1',
					backgroundColor: 'bg.primary'
				})}
			>
				<UdfSignatureBuilder {inputs} onChange={updateInputs} />
				<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
					<span id="udf-output-label" class={label()}>Output type</span>
					<ColumnTypeDropdown
						value={outputDtype}
						ariaLabelledby="udf-output-label"
						onChange={(value) => {
							outputDtype = value;
							markDirty();
						}}
						placeholder="Optional"
					/>
				</div>
			</div>

			<div
				class={css({
					display: 'flex',
					flexDirection: 'column',
					gap: '3',
					padding: '4',
					borderWidth: '1',
					backgroundColor: 'bg.primary'
				})}
			>
				<div
					class={css({ display: 'flex', alignItems: 'center', justifyContent: 'space-between' })}
				>
					<h3 class={css({ margin: '0', fontSize: 'sm', color: 'fg.secondary' })}>Code</h3>
					<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>
						Define a function named <code>udf</code>
					</span>
				</div>
				<CodeEditor bind:value={code} height="360px" onEdit={markDirty} />
			</div>
		</div>
	</div>
</div>
