<script lang="ts">
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { listUdfs, deleteUdf, exportUdfs, importUdfs, cloneUdf } from '$lib/api/udf';
	import type { Udf, UdfExport } from '$lib/types/udf';
	import { Plus, Upload, Download, Copy, Trash2, Pencil } from 'lucide-svelte';

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
		let payload: UdfExport | null = null;
		try {
			payload = JSON.parse(importText) as UdfExport;
		} catch {
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

	function signatureLabel(signature: Udf['signature']): string {
		if (!signature?.inputs?.length) return 'No inputs';
		return signature.inputs.map((input) => input.dtype).join(', ');
	}
</script>

<div class="container">
	<header class="page-header">
		<div class="header-text">
			<h1>UDF Library</h1>
			<p class="subtitle">Reusable Python transforms stored globally</p>
		</div>
		<div class="header-actions">
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

	<div class="toolbar">
		<input type="text" placeholder="Search UDFs..." bind:value={search} />
	</div>

	{#if query.isLoading}
		<div class="info-box">Loading UDFs...</div>
	{:else if query.isError}
		<div class="error-box">
			{query.error instanceof Error ? query.error.message : 'Error loading UDFs.'}
		</div>
	{:else if query.data}
		{#if query.data.length === 0}
			<div class="empty-state">
				<p>No UDFs yet.</p>
				<button class="btn-primary" onclick={openNew}>Create your first UDF</button>
			</div>
		{:else}
			<div class="list">
				{#each query.data as udf (udf.id)}
					<div class="row">
						<div class="row-main">
							<div class="row-title">
								<h3>{udf.name}</h3>
								<span class="row-signature">{signatureLabel(udf.signature)}</span>
							</div>
							{#if udf.description}
								<p class="row-description">{udf.description}</p>
							{/if}
							{#if udf.tags?.length}
								<div class="row-tags">
									{#each udf.tags as tag (tag)}
										<span class="tag">{tag}</span>
									{/each}
								</div>
							{/if}
						</div>
						<div class="row-actions">
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
				<button class="modal-close" onclick={() => (importOpen = false)}>×</button>
			</div>
			<div class="modal-body">
				<textarea rows="10" placeholder="Paste exported JSON here..." bind:value={importText}
				></textarea>
				<label class="checkbox">
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

<style>
	.container {
		max-width: 1100px;
		margin: 0 auto;
		padding: var(--space-7) var(--space-6);
		height: 100%;
		overflow: auto;
	}
	.page-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: var(--space-6);
		margin-bottom: var(--space-6);
		padding-bottom: var(--space-5);
		border-bottom: 1px solid var(--border-primary);
	}
	.header-text h1 {
		margin: 0 0 var(--space-2) 0;
		font-size: var(--text-2xl);
	}
	.subtitle {
		margin: 0;
		color: var(--fg-tertiary);
	}
	.header-actions {
		display: flex;
		gap: var(--space-2);
		flex-wrap: wrap;
	}
	.toolbar {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		margin-bottom: var(--space-4);
	}
	.toolbar input {
		max-width: 360px;
	}
	.list {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.row {
		display: flex;
		justify-content: space-between;
		gap: var(--space-4);
		padding: var(--space-4);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		background-color: var(--bg-primary);
	}
	.row-main {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.row-title {
		display: flex;
		align-items: center;
		gap: var(--space-3);
	}
	.row-title h3 {
		margin: 0;
		font-size: var(--text-base);
	}
	.row-signature {
		font-size: var(--text-xs);
		color: var(--fg-muted);
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}
	.row-description {
		margin: 0;
		color: var(--fg-tertiary);
	}
	.row-tags {
		display: flex;
		gap: var(--space-2);
		flex-wrap: wrap;
	}
	.tag {
		font-size: var(--text-xs);
		padding: 2px 6px;
		border-radius: var(--radius-sm);
		background-color: var(--bg-tertiary);
		color: var(--fg-muted);
	}
	.row-actions {
		display: flex;
		gap: var(--space-2);
		align-items: center;
	}
	.empty-state {
		padding: var(--space-8);
		text-align: center;
		border: 1px dashed var(--border-primary);
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
		width: min(720px, 92vw);
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
		justify-content: space-between;
		align-items: center;
		padding: var(--space-3) var(--space-4);
		border-bottom: 1px solid var(--border-primary);
	}
	.modal-header h2 {
		margin: 0;
		font-size: var(--text-base);
	}
	.modal-close {
		background: transparent;
		border: none;
		color: var(--fg-muted);
		cursor: pointer;
		font-size: 1.25rem;
	}
	.modal-body {
		padding: var(--space-4);
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.modal-body textarea {
		font-family: var(--font-mono);
	}
	.modal-footer {
		padding: var(--space-3) var(--space-4);
		border-top: 1px solid var(--border-primary);
		display: flex;
		justify-content: flex-end;
		gap: var(--space-2);
	}
	.checkbox {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		color: var(--fg-secondary);
	}
	@media (max-width: 900px) {
		.page-header {
			flex-direction: column;
			align-items: stretch;
		}
		.header-actions {
			justify-content: flex-start;
		}
		.row {
			flex-direction: column;
		}
		.row-actions {
			justify-content: flex-start;
		}
	}
</style>
