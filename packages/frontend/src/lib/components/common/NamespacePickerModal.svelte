<script lang="ts">
	import { Check, Plus, ArrowLeft, X } from '@lucide/svelte';
	import { createQuery } from '@tanstack/svelte-query';
	import { Debounced } from 'runed';
	import { tick } from 'svelte';
	import BaseModal from '$lib/components/ui/BaseModal.svelte';
	import PanelHeader from '$lib/components/ui/PanelHeader.svelte';
	import { listNamespaces, previewNamespaceStorage } from '$lib/api/namespaces';
	import { NAMESPACE_NAME_RULES, normalizeNamespace } from '$lib/utils/namespace';
	import { button, css } from '$lib/styles/panda';

	interface Props {
		open: boolean;
		selected: string;
		onSelect: (value: string) => void | Promise<void>;
		onSelectError?: (message: string) => void;
		onClose: () => void;
	}

	type View = 'namespaces' | 'create';

	let { open, selected, onSelect, onSelectError, onClose }: Props = $props();

	let view = $state<View>('namespaces');
	let searchQuery = $state('');
	let createName = $state('');
	let selecting = $state(false);
	let selectionError = $state<string | null>(null);
	const debouncedSearch = new Debounced(() => searchQuery, 200);

	const namespacesQuery = createQuery(() => ({
		queryKey: ['namespaces'],
		queryFn: async () => {
			const result = await listNamespaces();
			if (result.isErr()) throw new Error(result.error.message);
			return result.value.namespaces;
		},
		staleTime: 10_000,
		enabled: open
	}));

	const rawNamespaces = $derived(namespacesQuery.data ?? []);
	const normalizedSearch = $derived(debouncedSearch.current.toLowerCase().trim());
	const filteredNamespaces = $derived(
		normalizedSearch
			? rawNamespaces.filter((name) => name.toLowerCase().includes(normalizedSearch))
			: rawNamespaces
	);

	const normalizedCandidate = $derived(normalizeNamespace(createName));
	const invalidCandidate = $derived(!!createName.trim() && !normalizedCandidate);
	const duplicateCandidate = $derived(
		!!normalizedCandidate && rawNamespaces.includes(normalizedCandidate)
	);
	const canCreate = $derived(
		!!normalizedCandidate &&
			!duplicateCandidate &&
			!namespacesQuery.isLoading &&
			!namespacesQuery.isError
	);
	const storagePlanQuery = createQuery(() => ({
		queryKey: ['namespace-storage-plan', normalizedCandidate],
		queryFn: async () => {
			const result = await previewNamespaceStorage(normalizedCandidate);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		staleTime: 30_000,
		enabled: open && view === 'create' && canCreate
	}));
	const canSubmit = $derived(
		canCreate && !!storagePlanQuery.data && !storagePlanQuery.isLoading && !storagePlanQuery.isError
	);

	function resetAndClose(): void {
		view = 'namespaces';
		searchQuery = '';
		createName = '';
		selectionError = null;
		onClose();
	}

	function handleClose(): void {
		if (selecting) return;
		resetAndClose();
	}

	async function handleBack(): Promise<void> {
		if (selecting) return;
		view = 'namespaces';
		selectionError = null;
		await tick();
		document.querySelector<HTMLInputElement>('#namespace-picker-search')?.focus();
	}

	async function handleStartCreate(): Promise<void> {
		if (selecting) return;
		const candidate = normalizeNamespace(searchQuery);
		createName = candidate && !rawNamespaces.includes(candidate) ? candidate : '';
		selectionError = null;
		view = 'create';
		await tick();
		document.querySelector<HTMLInputElement>('#namespace-create-name')?.focus();
	}

	function errorMessage(error: unknown): string {
		return error instanceof Error ? error.message : String(error);
	}

	async function handleSelect(value: string): Promise<void> {
		if (selecting) return;
		if (value === selected) {
			handleClose();
			return;
		}

		selecting = true;
		selectionError = null;
		try {
			await onSelect(value);
			view = 'namespaces';
			searchQuery = '';
			createName = '';
			onClose();
		} catch (error) {
			const message = errorMessage(error);
			selectionError = message;
			onSelectError?.(message);
		} finally {
			selecting = false;
		}
	}

	async function handleCreate(): Promise<void> {
		if (selecting || !canSubmit || !normalizedCandidate) return;
		await handleSelect(normalizedCandidate);
	}
</script>

<BaseModal
	{open}
	size="large"
	initialFocus="#namespace-picker-search"
	onClose={handleClose}
	ariaLabelledby="namespace-picker-title"
	ariaDescribedby="namespace-picker-description"
>
	{#snippet content()}
		<div class={css({ display: 'flex', height: 'full', minHeight: '0', flexDirection: 'column' })}>
			<PanelHeader>
				{#snippet title()}
					<div class={css({ minWidth: '0' })}>
						<h2 id="namespace-picker-title" class={css({ margin: '0', fontSize: 'md' })}>
							{view === 'namespaces' ? 'Namespaces' : 'New namespace'}
						</h2>
						<p
							id="namespace-picker-description"
							class={css({ margin: '0', marginTop: '1', color: 'fg.tertiary', fontSize: 'sm' })}
						>
							{view === 'namespaces'
								? 'Choose a namespace for data and analyses.'
								: 'Choose a name for this namespace and review its storage plan.'}
						</p>
					</div>
				{/snippet}
				{#snippet actions()}
					<div class={css({ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '2' })}>
						{#if view === 'create'}
							<button
								class={button({ variant: 'ghost', size: 'compact' })}
								onclick={handleBack}
								disabled={selecting}
								type="button"
							>
								<ArrowLeft size={16} />
								Back to namespaces
							</button>
						{/if}
						<button
							class={css({
								display: 'flex',
								alignItems: 'center',
								justifyContent: 'center',
								borderWidth: '1',
								backgroundColor: 'transparent',
								color: 'fg.muted',
								cursor: 'pointer',
								padding: '1',
								_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' },
								_disabled: { cursor: 'not-allowed', opacity: '0.5' }
							})}
							onclick={handleClose}
							aria-label="Close namespace picker"
							disabled={selecting}
							type="button"
						>
							<X size={16} />
						</button>
					</div>
				{/snippet}
			</PanelHeader>

			{#if view === 'namespaces'}
				<div
					class={css({
						display: 'flex',
						flexWrap: 'wrap',
						alignItems: 'end',
						gap: '3',
						paddingX: '4',
						paddingTop: '4'
					})}
				>
					<label
						class={css({
							display: 'flex',
							minWidth: '0',
							flex: '1',
							flexDirection: 'column',
							gap: '1'
						})}
					>
						<span class={css({ color: 'fg.secondary', fontSize: 'xs', fontWeight: 'medium' })}>
							Search namespaces
						</span>
						<input
							id="namespace-picker-search"
							class={css({
								width: 'full',
								minWidth: '0',
								borderWidth: '1',
								backgroundColor: 'bg.primary',
								color: 'fg.primary',
								paddingX: '3',
								paddingY: '2',
								fontSize: 'sm',
								_placeholder: { color: 'fg.muted' },
								_focusVisible: { borderColor: 'border.accent', outline: 'none' },
								_disabled: { cursor: 'not-allowed', opacity: '0.5' }
							})}
							type="text"
							bind:value={searchQuery}
							disabled={selecting}
							placeholder="Search namespaces"
							aria-label="Search namespaces"
							autocomplete="off"
						/>
					</label>
					<button
						class={button({ variant: 'secondary' })}
						onclick={handleStartCreate}
						disabled={selecting}
						type="button"
					>
						<Plus size={16} />
						New namespace
					</button>
				</div>

				{#if selectionError}
					<div
						class={css({
							marginX: '4',
							marginTop: '3',
							padding: '3',
							borderWidth: '1',
							borderColor: 'border.error',
							color: 'fg.error',
							fontSize: 'sm'
						})}
						role="alert"
					>
						{selectionError}
					</div>
				{/if}
				{#if selecting}
					<div
						class={css({ paddingX: '4', paddingTop: '3', color: 'fg.muted', fontSize: 'sm' })}
						role="status"
					>
						Switching namespace…
					</div>
				{/if}

				<div
					class={css({
						display: 'flex',
						minHeight: '0',
						flex: '1',
						flexDirection: 'column',
						gap: '2',
						overflowY: 'auto',
						padding: '4'
					})}
				>
					{#if namespacesQuery.isLoading}
						<div class={css({ padding: '4', color: 'fg.muted', fontSize: 'sm' })}>
							Loading namespaces…
						</div>
					{:else if namespacesQuery.isError}
						<div
							class={css({
								display: 'flex',
								flexWrap: 'wrap',
								alignItems: 'center',
								gap: '3',
								borderWidth: '1',
								borderColor: 'border.error',
								padding: '4',
								color: 'fg.error',
								fontSize: 'sm'
							})}
						>
							<span role="alert">Could not load namespaces.</span>
							<button
								class={button({ variant: 'secondary', size: 'sm' })}
								onclick={() => void namespacesQuery.refetch()}
								disabled={selecting}
								type="button"
							>
								Retry
							</button>
						</div>
					{:else if filteredNamespaces.length === 0}
						<div class={css({ padding: '4', color: 'fg.muted', fontSize: 'sm' })}>
							No namespaces match your search.
						</div>
					{:else}
						{#each filteredNamespaces as name (name)}
							<button
								data-namespace-option={name}
								class={css({
									display: 'flex',
									width: 'full',
									minHeight: '16',
									alignItems: 'center',
									justifyContent: 'space-between',
									gap: '4',
									borderWidth: '1',
									borderColor: name === selected ? 'border.accent' : 'border.primary',
									backgroundColor: name === selected ? 'bg.accent' : 'bg.secondary',
									color: name === selected ? 'fg.primary' : 'fg.secondary',
									cursor: 'pointer',
									paddingX: '4',
									paddingY: '3',
									textAlign: 'left',
									transitionProperty: 'background-color, border-color',
									transitionDuration: '150ms',
									_hover: { backgroundColor: 'bg.hover', borderColor: 'border.accent' },
									_focusVisible: {
										outline: '2px solid',
										outlineColor: 'border.accent',
										outlineOffset: '2px'
									},
									_disabled: { cursor: 'not-allowed', opacity: '0.5' }
								})}
								onclick={() => void handleSelect(name)}
								disabled={selecting}
								aria-pressed={name === selected}
								type="button"
							>
								<span
									class={css({
										overflow: 'hidden',
										textOverflow: 'ellipsis',
										whiteSpace: 'nowrap',
										fontSize: 'md',
										fontWeight: 'medium'
									})}
								>
									{name}
								</span>
								{#if name === selected}
									<span
										class={css({
											display: 'inline-flex',
											flexShrink: '0',
											alignItems: 'center',
											gap: '2',
											color: 'accent.primary',
											fontSize: 'xs',
											fontWeight: 'semibold'
										})}
									>
										<Check size={16} />
										Current namespace
									</span>
								{/if}
							</button>
						{/each}
					{/if}
				</div>
			{:else}
				<form
					class={css({ display: 'flex', minHeight: '0', flex: '1', flexDirection: 'column' })}
					onsubmit={(event) => {
						event.preventDefault();
						void handleCreate();
					}}
				>
					<div class={css({ minHeight: '0', flex: '1', overflowY: 'auto', padding: '4' })}>
						<div
							class={css({
								display: 'flex',
								maxWidth: 'pageWide',
								flexDirection: 'column',
								gap: '4'
							})}
						>
							<label class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
								<span class={css({ color: 'fg.secondary', fontSize: 'sm', fontWeight: 'medium' })}>
									Name
								</span>
								<input
									id="namespace-create-name"
									class={css({
										width: 'full',
										borderWidth: '1',
										backgroundColor: 'bg.primary',
										color: 'fg.primary',
										paddingX: '3',
										paddingY: '2',
										fontSize: 'sm',
										_placeholder: { color: 'fg.muted' },
										_focusVisible: { borderColor: 'border.accent', outline: 'none' },
										_disabled: { cursor: 'not-allowed', opacity: '0.5' }
									})}
									bind:value={createName}
									disabled={selecting}
									placeholder="analytics"
									aria-label="Name"
									aria-describedby="namespace-create-name-rules"
									autocomplete="off"
								/>
							</label>

							<p
								id="namespace-create-name-rules"
								class={css({
									margin: '0',
									color: invalidCandidate ? 'fg.error' : 'fg.muted',
									fontSize: 'sm'
								})}
								role={invalidCandidate ? 'alert' : undefined}
							>
								{NAMESPACE_NAME_RULES}
							</p>

							{#if duplicateCandidate}
								<p class={css({ margin: '0', color: 'fg.error', fontSize: 'sm' })} role="alert">
									A namespace with this name already exists. Choose it from the namespace list.
								</p>
							{:else if namespacesQuery.isLoading}
								<p class={css({ margin: '0', color: 'fg.muted', fontSize: 'sm' })}>
									Loading namespaces before checking the name…
								</p>
							{:else if namespacesQuery.isError}
								<div
									class={css({
										display: 'flex',
										flexWrap: 'wrap',
										alignItems: 'center',
										gap: '3',
										color: 'fg.error',
										fontSize: 'sm'
									})}
								>
									<span role="alert">Could not verify whether this namespace already exists.</span>
									<button
										class={button({ variant: 'secondary', size: 'sm' })}
										onclick={() => void namespacesQuery.refetch()}
										disabled={selecting}
										type="button"
									>
										Retry
									</button>
								</div>
							{/if}

							<div
								class={css({
									display: 'flex',
									flexDirection: 'column',
									gap: '3',
									borderWidth: '1',
									backgroundColor: 'bg.secondary',
									padding: '4'
								})}
								aria-live="polite"
							>
								<h3
									class={css({
										margin: '0',
										color: 'fg.primary',
										fontSize: 'sm',
										fontWeight: 'semibold'
									})}
								>
									Storage plan
								</h3>
								{#if !normalizedCandidate || duplicateCandidate || invalidCandidate}
									<p class={css({ margin: '0', color: 'fg.muted', fontSize: 'sm' })}>
										Enter a valid, unused name to preview its storage plan.
									</p>
								{:else if namespacesQuery.isLoading || namespacesQuery.isError}
									<p class={css({ margin: '0', color: 'fg.muted', fontSize: 'sm' })}>
										The storage plan appears after the namespace name is verified.
									</p>
								{:else if storagePlanQuery.isLoading}
									<p class={css({ margin: '0', color: 'fg.muted', fontSize: 'sm' })}>
										Loading storage plan…
									</p>
								{:else if storagePlanQuery.isError}
									<div
										class={css({
											display: 'flex',
											flexWrap: 'wrap',
											alignItems: 'center',
											gap: '3',
											color: 'fg.error',
											fontSize: 'sm'
										})}
									>
										<span role="alert">Could not load storage plan.</span>
										<button
											class={button({ variant: 'secondary', size: 'sm' })}
											onclick={() => void storagePlanQuery.refetch()}
											disabled={selecting}
											type="button"
										>
											Retry
										</button>
									</div>
								{:else if storagePlanQuery.data}
									{@const plan = storagePlanQuery.data}
									<div
										class={css({
											display: 'grid',
											gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 18rem), 1fr))',
											gap: '2',
											color: 'fg.muted',
											fontFamily: 'mono',
											fontSize: 'xs',
											lineHeight: 'snug',
											overflowWrap: 'anywhere'
										})}
									>
										<span>S3 bucket (root): {plan.bucket}</span>
										<span>uploads: {plan.uploads_root}/…</span>
										<span>clean: {plan.clean_root}/…</span>
										<span>exports: {plan.exports_root}/…</span>
									</div>
								{/if}
							</div>

							{#if selectionError}
								<div
									class={css({
										borderWidth: '1',
										borderColor: 'border.error',
										backgroundColor: 'bg.error',
										padding: '3',
										color: 'fg.error',
										fontSize: 'sm'
									})}
									role="alert"
								>
									{selectionError}
								</div>
							{/if}
						</div>
					</div>

					<div
						class={css({
							display: 'flex',
							flexWrap: 'wrap',
							alignItems: 'center',
							justifyContent: 'space-between',
							gap: '3',
							borderTopWidth: '1',
							padding: '4'
						})}
					>
						{#if selecting}
							<p class={css({ margin: '0', color: 'fg.muted', fontSize: 'sm' })} aria-live="polite">
								Preparing namespace…
							</p>
						{:else}
							<span class={css({ color: 'fg.muted', fontSize: 'sm' })}
								>Namespace names cannot be changed later.</span
							>
						{/if}
						<button
							class={button({ variant: 'primary' })}
							data-namespace-create={normalizedCandidate}
							disabled={selecting || !canSubmit}
							type="submit"
						>
							Create namespace
						</button>
					</div>
				</form>
			{/if}
		</div>
	{/snippet}
</BaseModal>
