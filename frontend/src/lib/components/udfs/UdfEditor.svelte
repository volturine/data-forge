<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { createUdf, getUdf, updateUdf } from '$lib/api/udf';
	import CodeEditor from '$lib/components/common/CodeEditor.svelte';
	import UdfSignatureBuilder from '$lib/components/udfs/UdfSignatureBuilder.svelte';
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

	function updateInputs(next: UdfInput[]) {
		inputs = next;
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

	$effect(() => {
		const params = inputs.map((item, index) => item.label?.trim() || `arg${index + 1}`);
		const signature = params.join(', ');
		if (!signature && !code.trim().startsWith('def udf')) return;
		if (signature === lastArgs) return;
		lastArgs = signature;
		const updated = updateSignature(code, signature);
		code = updated;
	});

	const canSave = $derived(name.trim().length > 0 && code.trim().length > 0);
</script>

<div class="container">
	<header class="page-header">
		<div class="header-left">
			<button class="btn-back" onclick={handleBack}>
				<ArrowLeft size={18} />
			</button>
			<div>
				<h1>{mode === 'create' ? 'New UDF' : 'Edit UDF'}</h1>
				<p class="subtitle">Reusable Python transforms for your pipelines</p>
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
		<div class="content">
			<div class="form">
				<div class="form-group">
					<label for="udf-name">Name</label>
					<input id="udf-name" type="text" bind:value={name} placeholder="UDF name" />
				</div>
				<div class="form-group">
					<label for="udf-description">Description</label>
					<textarea id="udf-description" rows="3" bind:value={description}></textarea>
				</div>
				<div class="form-group">
					<label for="udf-tags">Tags (comma-separated)</label>
					<input id="udf-tags" type="text" bind:value={tags} placeholder="math, text, date" />
				</div>
			</div>

			<div class="panel">
				<UdfSignatureBuilder {inputs} onChange={updateInputs} />
				<div class="output">
					<label for="udf-output">Output dtype</label>
					<select id="udf-output" bind:value={outputDtype}>
						<option value="">Optional</option>
						<option value="String">String</option>
						<option value="Categorical">Categorical</option>
						<option value="Int8">Int8</option>
						<option value="Int16">Int16</option>
						<option value="Int32">Int32</option>
						<option value="Int64">Int64</option>
						<option value="UInt8">UInt8</option>
						<option value="UInt16">UInt16</option>
						<option value="UInt32">UInt32</option>
						<option value="UInt64">UInt64</option>
						<option value="Float32">Float32</option>
						<option value="Float64">Float64</option>
						<option value="Boolean">Boolean</option>
						<option value="Date">Date</option>
						<option value="Datetime">Datetime</option>
						<option value="Time">Time</option>
						<option value="Duration">Duration</option>
						<option value="Binary">Binary</option>
						<option value="Null">Null</option>
					</select>
				</div>
			</div>

			<div class="panel">
				<div class="panel-header">
					<h4>Code</h4>
					<span class="hint">Define a function named <code>udf</code></span>
				</div>
				<CodeEditor bind:value={code} height="360px" />
			</div>

			{#if error}
				<div class="error-box">{error}</div>
			{/if}
		</div>
	{/if}
</div>

<style>
	.container {
		max-width: 960px;
		margin: 0 auto;
		padding: var(--space-6);
		height: 100%;
		overflow: auto;
	}
	.page-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: var(--space-4);
		margin-bottom: var(--space-6);
		padding-bottom: var(--space-5);
		border-bottom: 1px solid var(--border-primary);
	}
	.header-left {
		display: flex;
		align-items: center;
		gap: var(--space-3);
	}
	.btn-back {
		width: 36px;
		height: 36px;
		padding: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		background-color: var(--bg-tertiary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		color: var(--fg-secondary);
	}
	.btn-back:hover {
		background-color: var(--bg-hover);
		color: var(--fg-primary);
	}
	.subtitle {
		margin: 0;
		color: var(--fg-tertiary);
	}
	.content {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
	}
	.form {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
		gap: var(--space-4);
	}
	.form-group {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.form-group label {
		font-size: var(--text-sm);
		color: var(--fg-secondary);
	}
	.panel {
		background-color: var(--bg-primary);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		padding: var(--space-4);
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.panel-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}
	.panel-header h4 {
		margin: 0;
		font-size: var(--text-sm);
		color: var(--fg-secondary);
	}
	.hint {
		font-size: var(--text-xs);
		color: var(--fg-muted);
	}
	.output {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	@media (max-width: 720px) {
		.page-header {
			flex-direction: column;
			align-items: stretch;
		}
		.form {
			grid-template-columns: 1fr;
		}
	}
</style>
