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
</script>

<div class="max-w-240 mx-auto p-6 h-full overflow-auto">
	<header
		class="flex flex-col sm:flex-row justify-between items-stretch sm:items-center gap-4 mb-6 pb-5 border-b border-tertiary"
	>
		<div class="flex items-center gap-3">
			<button class="btn-back" onclick={handleBack} type="button">
				<ArrowLeft size={18} />
			</button>
			<div>
				<h1>{mode === 'create' ? 'New UDF' : 'Edit UDF'}</h1>
				<p class="m-0 text-fg-tertiary">Reusable Python transforms for your pipelines</p>
			</div>
		</div>
		<button class="btn-primary" onclick={() => saveMutation.mutate()} disabled={!canSave || saving}>
			<Save size={16} />
			{saving ? 'Saving...' : 'Save UDF'}
		</button>
	</header>

	{#if query.isLoading}
		<div class="info-box">Loading UDF...</div>
	{:else}
		<div class="flex flex-col gap-5">
			<div class="grid grid-cols-1 sm:grid-cols-[repeat(auto-fit,minmax(260px,1fr))] gap-4">
				<div class="flex flex-col gap-2">
					<label for="udf-name" class="text-sm text-fg-secondary">Name</label>
					<input id="udf-name" type="text" bind:value={name} placeholder="UDF name" />
				</div>
				<div class="flex flex-col gap-2">
					<label for="udf-description" class="text-sm text-fg-secondary">Description</label>
					<textarea id="udf-description" rows="3" bind:value={description}></textarea>
				</div>
				<div class="flex flex-col gap-2">
					<label for="udf-tags" class="text-sm text-fg-secondary">Tags (comma-separated)</label>
					<input id="udf-tags" type="text" bind:value={tags} placeholder="math, text, date" />
				</div>
			</div>

			<div class="flex flex-col gap-3 p-4 border bg-primary border-tertiary">
				<UdfSignatureBuilder {inputs} onChange={updateInputs} />
				<div class="flex flex-col gap-2">
					<label for="udf-output">Output dtype</label>
					<ColumnTypeDropdown
						value={outputDtype}
						onChange={(val) => (outputDtype = val)}
						placeholder="Optional"
					/>
				</div>
			</div>

			<div class="flex flex-col gap-3 p-4 border bg-primary border-tertiary">
				<div class="flex justify-between items-center">
					<h4 class="m-0 text-sm text-fg-secondary">Code</h4>
					<span class="text-xs text-fg-muted">Define a function named <code>udf</code></span>
				</div>
				<CodeEditor bind:value={code} height="360px" />
			</div>

			{#if error}
				<div class="error-box">{error}</div>
			{/if}
		</div>
	{/if}
</div>
