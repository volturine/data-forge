<script lang="ts">
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { listUdfs, deleteUdf, exportUdfs, importUdfs, cloneUdf } from '$lib/api/udf';
	import type { UdfExport } from '$lib/types/udf';
	import { Plus, Upload, Download, Copy, Trash2, Pencil, X } from 'lucide-svelte';
	import ColumnTypeBadge from '$lib/components/common/ColumnTypeBadge.svelte';
	import BaseModal from '$lib/components/ui/BaseModal.svelte';
	import PanelHeader from '$lib/components/ui/PanelHeader.svelte';
	import PanelFooter from '$lib/components/ui/PanelFooter.svelte';
	import Callout from '$lib/components/ui/Callout.svelte';
	import { css, spinner, button, chip, cx, input, label } from '$lib/styles/panda';

	const queryClient = useQueryClient();

	let search = $state('');
	let importOpen = $state(false);
	let importText = $state('');
	let overwriteImport = $state(false);
	let importError = $state('');
	let importing = $state(false);
	let exportError = $state('');
	let cloningId = $state<string | null>(null);
	let deletingId = $state<string | null>(null);

	function closeImport() {
		importOpen = false;
		importText = '';
		importError = '';
		overwriteImport = false;
	}

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
		exportError = '';
		const result = await exportUdfs();
		if (result.isErr()) {
			exportError = result.error.message;
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
		importing = true;
		try {
			const result = await importUdfs({ udfs: payload.udfs, overwrite: overwriteImport });
			if (result.isErr()) {
				importError = result.error.message;
				return;
			}
			closeImport();
			queryClient.invalidateQueries({ queryKey: ['udfs'] });
		} finally {
			importing = false;
		}
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

<div class={css({ marginX: 'auto', maxWidth: 'pageWide', paddingX: '6', paddingY: '7' })}>
	<header
		class={css({
			marginBottom: '6',
			display: 'flex',
			flexDirection: 'column',
			alignItems: 'stretch',
			justifyContent: 'space-between',
			gap: '6',
			borderBottomWidth: '1',
			paddingBottom: '5',
			md: { flexDirection: 'row', alignItems: 'flex-start' }
		})}
	>
		<div>
			<h1 class={css({ margin: '0', marginBottom: '2', fontSize: '2xl' })}>UDF Library</h1>
			<p class={css({ margin: '0', color: 'fg.tertiary' })}>
				Reusable Python transforms stored globally
			</p>
		</div>
		<div
			class={css({ display: 'flex', flexDirection: 'column', gap: '2', alignItems: 'flex-end' })}
		>
			<div class={css({ display: 'flex', flexWrap: 'wrap', gap: '2' })}>
				<button class={button({ variant: 'secondary' })} onclick={() => (importOpen = true)}>
					<Upload size={16} />
					Import
				</button>
				<button class={button({ variant: 'secondary' })} onclick={handleExport}>
					<Download size={16} />
					Export
				</button>
				<button class={button({ variant: 'primary' })} onclick={openNew}>
					<Plus size={16} />
					New UDF
				</button>
			</div>
			{#if exportError}
				<Callout tone="error">
					{exportError}
				</Callout>
			{/if}
		</div>
	</header>

	<div class={css({ display: 'flex', alignItems: 'center', marginBottom: '4', gap: '3' })}>
		<input
			id="udf-search"
			aria-label="Search UDFs"
			type="text"
			placeholder="Search UDFs..."
			bind:value={search}
			class={cx(input(), css({ maxWidth: 'popover' }))}
		/>
	</div>

	{#if query.isLoading}
		<div
			class={css({
				display: 'flex',
				alignItems: 'center',
				height: '100%',
				justifyContent: 'center'
			})}
		>
			<div class={spinner()}></div>
		</div>
	{:else if query.isError}
		<Callout tone="error">
			{query.error instanceof Error ? query.error.message : 'Error loading UDFs.'}
		</Callout>
	{:else if query.data}
		{#if query.data.length === 0}
			<div
				class={css({
					borderWidth: '1',
					borderStyle: 'dashed',
					padding: '8',
					textAlign: 'center'
				})}
			>
				<p>No UDFs yet.</p>
				<button class={button({ variant: 'primary' })} onclick={openNew}
					>Create your first UDF</button
				>
			</div>
		{:else}
			<div class={css({ display: 'flex', flexDirection: 'column', gap: '3' })}>
				{#each query.data as udf (udf.id)}
					<div
						data-udf-card={udf.name}
						class={css({
							display: 'flex',
							flexDirection: 'column',
							justifyContent: 'space-between',
							gap: '4',
							borderWidth: '1',
							backgroundColor: 'bg.primary',
							padding: '4',
							md: { flexDirection: 'row' }
						})}
					>
						<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
							<div class={css({ display: 'flex', alignItems: 'center', gap: '3' })}>
								<h3 class={css({ margin: '0', fontSize: 'md' })}>{udf.name}</h3>
								<div
									class={css({ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '1' })}
								>
									{#if udf.signature?.inputs?.length}
										{#each udf.signature.inputs as input, i (i)}
											<ColumnTypeBadge columnType={input.dtype} size="xs" showIcon={false} />
											{#if i < udf.signature.inputs.length - 1}
												<span class={css({ marginX: '0.5', fontSize: 'xs', color: 'fg.muted' })}
													>,</span
												>
											{/if}
										{/each}
									{:else}
										<span
											class={css({
												fontSize: 'xs',
												textTransform: 'uppercase',
												letterSpacing: 'wide',
												color: 'fg.muted'
											})}
										>
											No inputs
										</span>
									{/if}
								</div>
							</div>
							{#if udf.description}
								<p class={css({ margin: '0', color: 'fg.tertiary' })}>{udf.description}</p>
							{/if}
							{#if udf.tags?.length}
								<div class={css({ display: 'flex', flexWrap: 'wrap', gap: '2' })}>
									{#each udf.tags as tag (tag)}
										<span class={chip({ tone: 'neutral' })}>
											{tag}
										</span>
									{/each}
								</div>
							{/if}
						</div>
						<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
							<button
								class={button({ variant: 'ghost', size: 'sm' })}
								onclick={() => editUdf(udf.id)}
							>
								<Pencil size={14} />
								Edit
							</button>
							<button
								class={button({ variant: 'ghost', size: 'sm' })}
								onclick={() => handleClone(udf.id)}
								disabled={cloningId === udf.id}
							>
								<Copy size={14} />
								Clone
							</button>
							{#if deletingId === udf.id}
								<button
									class={button({ variant: 'danger', size: 'sm' })}
									onclick={() => confirmDelete(udf.id)}>Confirm</button
								>
								<button class={button({ variant: 'secondary', size: 'sm' })} onclick={cancelDelete}
									>Cancel</button
								>
							{:else}
								<button
									class={button({ variant: 'ghost', size: 'sm' })}
									onclick={() => handleDelete(udf.id)}
								>
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
</div>

<BaseModal
	open={importOpen}
	onClose={closeImport}
	ariaLabelledby="import-heading"
	panelClass={css({
		width: 'min(720px, 92vw)',
		backgroundColor: 'bg.primary',
		borderWidth: '1',
		display: 'flex',
		flexDirection: 'column',
		_focus: { outline: 'none' }
	})}
>
	{#snippet content()}
		<PanelHeader>
			{#snippet title()}<h2 id="import-heading" class={css({ margin: '0', fontSize: 'md' })}>
					Import UDFs
				</h2>{/snippet}
			{#snippet actions()}
				<button
					class={css({
						background: 'transparent',
						border: 'none',
						color: 'fg.muted',
						cursor: 'pointer',
						padding: '1',
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'center',
						transitionProperty: 'color, background-color',
						transitionDuration: 'normal',
						_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' }
					})}
					onclick={closeImport}
					aria-label="Close import dialog"
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
			<label class={label()} for="udf-import-json">Import JSON</label>
			<textarea
				rows="10"
				id="udf-import-json"
				placeholder="Paste exported JSON here..."
				bind:value={importText}
				class={input()}
			></textarea>
			<label class={label({ variant: 'inline' })}>
				<input id="udf-overwrite-import" type="checkbox" bind:checked={overwriteImport} />
				Overwrite existing by name
			</label>
			{#if importError}
				<Callout tone="error">
					{importError}
				</Callout>
			{/if}
		</div>
		<PanelFooter>
			<button class={button({ variant: 'secondary' })} onclick={closeImport}>Cancel</button>
			<button class={button({ variant: 'primary' })} disabled={importing} onclick={handleImport}
				>Import</button
			>
		</PanelFooter>
	{/snippet}
</BaseModal>
