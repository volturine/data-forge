<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { createUdf, getUdf, updateUdf } from '$lib/api/udf';
	import CodeEditor from '$lib/components/common/CodeEditor.svelte';
	import UdfSignatureBuilder from '$lib/components/udfs/UdfSignatureBuilder.svelte';
	import ColumnTypeDropdown from '$lib/components/common/ColumnTypeDropdown.svelte';
	import type { Udf, UdfInput, UdfSignature } from '$lib/types/udf';
	import { ArrowLeft, Save } from 'lucide-svelte';
	import { css, button, input, label } from '$lib/styles/panda';

	interface Props {
		mode: 'create' | 'edit';
	}

	let { mode }: Props = $props();
	const queryClient = useQueryClient();
	const udfId = $derived(page.params.id ?? '');

	let name = $state('');
	let description = $state('');
	let tags = $state('');
	let inputs = $state<UdfInput[]>([]);
	let outputDtype = $state('');
	let code = $state('def udf(value):\n    return value\n');
	let error = $state('');
	let saving = $state(false);
	let lastArgs = $state('');
	let dirty = $state(false);

	let initialized = $state(false);

	const query = createQuery(() => ({
		queryKey: ['udf', udfId],
		enabled: mode === 'edit' && !!udfId,
		queryFn: async () => {
			if (!udfId) throw new Error('Missing UDF id');
			const result = await getUdf(udfId);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		}
	}));

	// Network: $derived can't hydrate form state from query result.
	$effect(() => {
		if (mode !== 'edit') return;
		if (initialized) return;
		if (!query.data) return;
		const data = query.data as Udf;
		name = data.name;
		description = data.description ?? '';
		tags = (data.tags ?? []).join(', ');
		inputs = data.signature?.inputs ?? [];
		outputDtype = data.signature?.output_dtype ?? '';
		code = data.code;
		lastArgs = '';
		initialized = true;
	});

	const saveMutation = createMutation(() => ({
		mutationFn: async () => {
			saving = true;
			error = '';
			const signature: UdfSignature = {
				inputs,
				output_dtype: outputDtype || null
			};
			const tagList = tags
				.split(',')
				.map((item) => item.trim())
				.filter(Boolean);
			if (mode === 'create') {
				const result = await createUdf({
					name,
					description: description || null,
					signature,
					code,
					tags: tagList.length ? tagList : null
				});
				if (result.isErr()) throw new Error(result.error.message);
				return result.value;
			}
			if (!udfId) throw new Error('Missing UDF id');
			const update = await updateUdf(udfId, {
				name,
				description: description || null,
				signature,
				code,
				tags: tagList.length ? tagList : null
			});
			if (update.isErr()) throw new Error(update.error.message);
			return update.value;
		},
		onSuccess: (data: Udf) => {
			queryClient.invalidateQueries({ queryKey: ['udfs'] });
			dirty = false;
			if (mode === 'create') {
				goto(resolve(`/udfs/${data.id}`), { invalidateAll: true });
			}
			saving = false;
		},
		onError: (err: unknown) => {
			saving = false;
			error = err instanceof Error ? err.message : 'Failed to save';
		}
	}));

	function handleBack() {
		goto(resolve('/udfs'), { invalidateAll: true });
	}

	function updateSignature(source: string, signature: string): string {
		const lines = source.split('\n');
		if (lines.length === 0) return `def udf(${signature}):\n    return None\n`;
		if (!lines[0]?.trim().startsWith('def udf')) {
			return `def udf(${signature}):\n    return None\n`;
		}
		lines[0] = `def udf(${signature}):`;
		return lines.join('\n');
	}

	function updateInputs(next: UdfInput[]) {
		inputs = next;
		const params = next.map((item, index) => item.label?.trim() || `arg${index + 1}`);
		const sig = params.join(', ');
		if (!sig && !code.trim().startsWith('def udf')) return;
		if (sig === lastArgs) return;
		lastArgs = sig;
		code = updateSignature(code, sig);
	}

	const canSave = $derived(name.trim().length > 0 && code.trim().length > 0);

	// Subscription: $derived can't track mutation across multiple form fields.
	$effect(() => {
		void [name, description, tags, code, inputs, outputDtype];
		if (!initialized && mode === 'edit') return;
		dirty = true;
	});
</script>

<div
	class={css({
		maxWidth: 'modalLg',
		marginX: 'auto',
		padding: '6',
		height: 'full',
		overflowY: 'auto'
	})}
>
	<header
		class={css({
			display: 'flex',
			flexDirection: 'column',
			justifyContent: 'space-between',
			alignItems: 'stretch',
			gap: '4',
			marginBottom: '6',
			paddingBottom: '5',
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
					_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' }
				})}
				onclick={handleBack}
				type="button"
			>
				<ArrowLeft size={18} />
			</button>
			<div>
				<h1>{mode === 'create' ? 'New UDF' : 'Edit UDF'}</h1>
				<p class={css({ margin: '0', color: 'fg.tertiary' })}>
					Reusable Python transforms for your pipelines
				</p>
			</div>
		</div>
		<button
			class={button({ variant: 'primary' })}
			data-testid="udf-save-button"
			onclick={() => saveMutation.mutate()}
			disabled={!canSave || saving}
		>
			<Save size={16} />
			{saving ? 'Saving...' : 'Save UDF'}
		</button>
	</header>

	{#if query.isLoading}
		<div
			class={css({
				paddingX: '3',
				paddingY: '2.5',
				border: 'none',
				borderLeftWidth: '2',

				marginTop: '3',
				marginBottom: '0',
				fontSize: 'xs',
				lineHeight: 'normal',
				backgroundColor: 'transparent',
				borderLeftColor: 'border.accent',
				color: 'fg.tertiary'
			})}
		>
			Loading UDF...
		</div>
	{:else if query.isError}
		<div
			data-testid="udf-load-error"
			class={css({
				paddingX: '3',
				paddingY: '2.5',
				border: 'none',
				borderLeftWidth: '2',

				marginTop: '3',
				marginBottom: '0',
				fontSize: 'xs',
				lineHeight: 'normal',
				backgroundColor: 'transparent',
				borderLeftColor: 'border.error',
				color: 'fg.error'
			})}
		>
			Failed to load UDF.
		</div>
	{:else}
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
						placeholder="UDF name"
						class={input()}
					/>
				</div>
				<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
					<label for="udf-description" class={label({ variant: 'field' })}>Description</label>
					<textarea id="udf-description" rows="3" bind:value={description} class={input()}
					></textarea>
				</div>
				<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
					<label for="udf-tags" class={label({ variant: 'field' })}>Tags (comma-separated)</label>
					<input
						id="udf-tags"
						type="text"
						bind:value={tags}
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
					<label class={label()} for="udf-output">Output dtype</label>
					<ColumnTypeDropdown
						value={outputDtype}
						onChange={(val) => (outputDtype = val)}
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
					<h4 class={css({ margin: '0', fontSize: 'sm', color: 'fg.secondary' })}>Code</h4>
					<span class={css({ fontSize: 'xs', color: 'fg.muted' })}
						>Define a function named <code>udf</code></span
					>
				</div>
				<CodeEditor bind:value={code} height="360px" />
			</div>

			{#if error}
				<div
					data-testid="udf-save-error"
					class={css({
						paddingX: '3',
						paddingY: '2.5',
						border: 'none',
						borderLeftWidth: '2',

						marginTop: '3',
						marginBottom: '0',
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
		</div>
	{/if}
</div>

<svelte:window
	onbeforeunload={(e) => {
		if (!dirty) return;
		e.preventDefault();
	}}
/>
