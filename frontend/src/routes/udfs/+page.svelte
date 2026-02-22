<script lang="ts">
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { listUdfs, deleteUdf, exportUdfs, importUdfs, cloneUdf } from '$lib/api/udf';
	import type { UdfExport } from '$lib/types/udf';
	import { Plus, Upload, Download, Copy, Trash2, Pencil } from 'lucide-svelte';
	import ColumnTypeBadge from '$lib/components/common/ColumnTypeBadge.svelte';

	const queryClient = useQueryClient();

	let search = $state('');
	let importOpen = $state(false);
	let importText = $state('');
	let overwriteImport = $state(false);
	let importError = $state('');
	let cloningId = $state<string | null>(null);
	let deletingId = $state<string | null>(null);

	const query = createQuery(() => ({
		queryKey: ['udfs', search],
		queryFn: async () => {
			const result = await listUdfs(search ? { q: search } : undefined);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		}
	}));

	const deleteMutation = createMutation(() => ({
		mutationFn: async (id: string) => {
			const result = await deleteUdf(id);
			if (result.isErr()) throw new Error(result.error.message);
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ['udfs'] });
		}
	}));

	const cloneMutation = createMutation(() => ({
		mutationFn: async (id: string) => {
			const result = await cloneUdf(id, {});
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ['udfs'] });
			cloningId = null;
		}
	}));

	async function handleExport() {
		const result = await exportUdfs();
		if (result.isErr()) {
			alert(result.error.message);
			return;
		}
		const payload = JSON.stringify(result.value, null, 2);
		const blob = new Blob([payload], { type: 'application/json' });
		const url = URL.createObjectURL(blob);
		const link = document.createElement('a');
		link.href = url;
		link.download = 'udfs.json';
		link.click();
		URL.revokeObjectURL(url);
	}

	async function handleImport() {
		importError = '';
		let payload: UdfExport;
		try {
			payload = JSON.parse(importText) as UdfExport;
		} catch (err) {
			void err;
			importError = 'Invalid JSON payload';
			return;
		}
		if (!payload || !Array.isArray(payload.udfs)) {
			importError = 'Payload must include a udfs array';
			return;
		}
		const result = await importUdfs({ udfs: payload.udfs, overwrite: overwriteImport });
		if (result.isErr()) {
			importError = result.error.message;
			return;
		}
		importOpen = false;
		importText = '';
		overwriteImport = false;
		queryClient.invalidateQueries({ queryKey: ['udfs'] });
	}

	function handleDelete(id: string) {
		deletingId = id;
	}

	function confirmDelete(id: string) {
		deleteMutation.mutate(id);
		deletingId = null;
	}

	function cancelDelete() {
		deletingId = null;
	}

	function handleClone(id: string) {
		cloningId = id;
		cloneMutation.mutate(id);
	}

	function openNew() {
		goto(resolve('/udfs/new'), { invalidateAll: true });
	}

	function editUdf(id: string) {
		goto(resolve(`/udfs/${id}`), { invalidateAll: true });
	}
</script>

<div class="udfs-page mx-auto max-w-275 px-6 py-7">
	<header
		class="mb-6 flex flex-col items-stretch justify-between gap-6 border-b border-tertiary pb-5 md:flex-row md:items-start"
	>
		<div>
			<h1 class="m-0 mb-2 text-2xl">UDF Library</h1>
			<p class="m-0 text-fg-tertiary">Reusable Python transforms stored globally</p>
		</div>
		<div class="flex flex-wrap gap-2">
			<button class="btn-secondary" onclick={() => (importOpen = true)}>
				<Upload size={16} />
				Import
			</button>
			<button class="btn-secondary" onclick={handleExport}>
				<Download size={16} />
				Export
			</button>
			<button class="btn-primary" onclick={openNew}>
				<Plus size={16} />
				New UDF
			</button>
		</div>
	</header>

	<div class="mb-4 flex items-center gap-3">
		<input type="text" placeholder="Search UDFs..." bind:value={search} class="max-w-90" />
	</div>

	{#if query.isLoading}
		<div class="flex h-full items-center justify-center">
			<div class="spinner"></div>
		</div>
	{:else if query.isError}
		<div class="error-box">
			{query.error instanceof Error ? query.error.message : 'Error loading UDFs.'}
		</div>
	{:else if query.data}
		{#if query.data.length === 0}
			<div class="border border-dashed border-tertiary p-8 text-center">
				<p>No UDFs yet.</p>
				<button class="btn-primary" onclick={openNew}>Create your first UDF</button>
			</div>
		{:else}
			<div class="flex flex-col gap-3">
				{#each query.data as udf (udf.id)}
					<div
						class="row flex flex-col justify-between gap-4 border border-tertiary bg-bg-primary p-4 md:flex-row"
					>
						<div class="flex flex-col gap-2">
							<div class="flex items-center gap-3">
								<h3 class="m-0 text-base">{udf.name}</h3>
								<div class="flex flex-wrap items-center gap-1">
									{#if udf.signature?.inputs?.length}
										{#each udf.signature.inputs as input, i (i)}
											<ColumnTypeBadge columnType={input.dtype} size="xs" showIcon={false} />
											{#if i < udf.signature.inputs.length - 1}
												<span class="mx-0.5 text-xs text-fg-muted">,</span>
											{/if}
										{/each}
									{:else}
										<span class="text-xs uppercase tracking-wide text-fg-muted">No inputs</span>
									{/if}
								</div>
							</div>
							{#if udf.description}
								<p class="m-0 text-fg-tertiary">{udf.description}</p>
							{/if}
							{#if udf.tags?.length}
								<div class="flex flex-wrap gap-2">
									{#each udf.tags as tag (tag)}
										<span class="bg-bg-tertiary px-1.5 py-0.5 text-xs text-fg-muted">{tag}</span>
									{/each}
								</div>
							{/if}
						</div>
						<div class="flex items-center gap-2">
							<button class="btn-ghost btn-sm" onclick={() => editUdf(udf.id)}>
								<Pencil size={14} />
								Edit
							</button>
							<button
								class="btn-ghost btn-sm"
								onclick={() => handleClone(udf.id)}
								disabled={cloningId === udf.id}
							>
								<Copy size={14} />
								Clone
							</button>
							{#if deletingId === udf.id}
								<button class="btn-danger btn-sm" onclick={() => confirmDelete(udf.id)}
									>Confirm</button
								>
								<button class="btn-secondary btn-sm" onclick={cancelDelete}>Cancel</button>
							{:else}
								<button class="btn-ghost btn-sm" onclick={() => handleDelete(udf.id)}>
									<Trash2 size={14} />
									Delete
								</button>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		{/if}
	{/if}

	{#if importOpen}
		<div class="modal-backdrop"></div>
		<div class="modal">
			<div class="modal-header">
				<h2>Import UDFs</h2>
				<button class="modal-close" onclick={() => (importOpen = false)}>x</button>
			</div>
			<div class="modal-body">
				<textarea
					rows="10"
					placeholder="Paste exported JSON here..."
					bind:value={importText}
					class="font-mono"
				></textarea>
				<label class="flex items-center gap-2 text-fg-secondary">
					<input type="checkbox" bind:checked={overwriteImport} />
					Overwrite existing by name
				</label>
				{#if importError}
					<div class="error-box">{importError}</div>
				{/if}
			</div>
			<div class="modal-footer">
				<button class="btn-secondary" onclick={() => (importOpen = false)}>Cancel</button>
				<button class="btn-primary" onclick={handleImport}>Import</button>
			</div>
		</div>
	{/if}
</div>
