<script lang="ts">
	import { Debounced } from 'runed';
	import { createQuery } from '@tanstack/svelte-query';
	import { listNamespaces } from '$lib/api/namespaces';
	import { normalizeNamespace } from '$lib/utils/namespace';

	interface Props {
		open: boolean;
		selected: string;
		onSelect: (value: string) => void;
		onClose: () => void;
		anchor?: HTMLElement | null;
	}

	let { open, selected, onSelect, onClose, anchor = null }: Props = $props();

	let searchQuery = $state('');
	const debouncedSearch = new Debounced(() => searchQuery, 200);
	let popoverRect = $state({ left: 0, top: 0, width: 320 });
	let lastAnchor = $state<HTMLElement | null>(null);
	let searchInput = $state<HTMLInputElement>();

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

	const trimmedSearch = $derived(debouncedSearch.current.trim());
	const normalizedCandidate = $derived(trimmedSearch ? normalizeNamespace(trimmedSearch) : '');
	const canCreate = $derived(
		!!normalizedCandidate && !rawNamespaces.some((name) => name === normalizedCandidate)
	);

	function handleClose() {
		onClose();
		searchQuery = '';
	}

	function handleSelect(value: string) {
		onSelect(value);
		handleClose();
	}

	function handleCreate() {
		if (!normalizedCandidate) return;
		handleSelect(normalizedCandidate);
	}

	function handleKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') {
			handleClose();
		}
	}

	function handleBackdropKeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' || event.key === ' ') {
			event.preventDefault();
			handleClose();
		}
	}

	function updatePopoverPosition() {
		const node = lastAnchor;
		if (!node) return;
		const rect = node.getBoundingClientRect();
		const width = Math.max(rect.width, 240);
		let left = rect.left;
		const maxLeft = window.innerWidth - width - 8;
		if (left > maxLeft) left = Math.max(8, maxLeft);
		popoverRect = {
			left,
			top: rect.bottom + 6,
			width
		};
	}

	function applyPopoverPosition(
		node: HTMLElement | undefined,
		rect: { left: number; top: number; width: number }
	) {
		if (!node) return;
		node.style.left = `${rect.left}px`;
		node.style.top = `${rect.top}px`;
		node.style.width = `${rect.width}px`;
	}

	function portal(node: HTMLElement, rect: { left: number; top: number; width: number }) {
		document.body.appendChild(node);
		applyPopoverPosition(node, rect);
		return {
			update(next: { left: number; top: number; width: number }) {
				applyPopoverPosition(node, next);
			},
			destroy() {
				node.remove();
			}
		};
	}

	// DOM: $derived can't track anchor position.
	$effect(() => {
		if (!open) return;
		lastAnchor = anchor;
		if (!lastAnchor) return;
		updatePopoverPosition();
		const handleResize = () => updatePopoverPosition();
		window.addEventListener('resize', handleResize);
		window.addEventListener('scroll', handleResize, true);
		return () => {
			window.removeEventListener('resize', handleResize);
			window.removeEventListener('scroll', handleResize, true);
		};
	});


	// DOM: $derived can't lock scroll.
	$effect(() => {
		if (!open) return;
		document.body.style.overflow = 'hidden';
		return () => {
			document.body.style.overflow = '';
		};
	});

	// DOM: $derived can't focus the search input.
	$effect(() => {
		if (open && searchInput) {
			searchInput.focus();
		}
	});
</script>

<svelte:window onkeydown={handleKeydown} />

{#if open}
	<div
		class="fixed inset-0 z-popover bg-transparent"
		onclick={handleClose}
		onkeydown={handleBackdropKeydown}
		role="button"
		tabindex="0"
		aria-label="Close namespace menu"
	></div>
	<div
		class="fixed z-overlay flex flex-col border border-tertiary bg-panel shadow-drag focus:outline-none max-h-[60vh]"
		role="dialog"
		aria-modal="false"
		aria-labelledby="namespace-picker-search"
		tabindex="-1"
		use:portal={popoverRect}
		onclick={(e) => e.stopPropagation()}
		onkeydown={(e) => e.stopPropagation()}
	>
		<div class="flex flex-col gap-2 p-2">
			<input
				id="namespace-picker-search"
				class="w-full border border-tertiary bg-primary px-2 py-1.5 text-sm text-fg-primary placeholder:text-fg-muted focus:border-accent-primary focus:outline-none"
				type="text"
				bind:this={searchInput}
				bind:value={searchQuery}
				placeholder="Search namespaces..."
				aria-label="Search namespaces"
				autocomplete="off"
			/>

			<div class="flex max-h-60 flex-col overflow-y-auto">
				{#if namespacesQuery.isLoading}
					<div class="p-2 text-xs text-fg-muted">Loading...</div>
				{:else if namespacesQuery.isError}
					<div class="p-2 text-xs text-error">Error loading namespaces</div>
				{:else if filteredNamespaces.length === 0 && !canCreate}
					<div class="p-2 text-xs text-fg-muted">No results</div>
				{:else}
					{#if canCreate}
						<button
							class="flex w-full cursor-pointer items-center justify-between border-b border-tertiary px-2 py-1.5 text-left text-fg-secondary hover:bg-hover hover:text-fg-primary transition-colors"
							onclick={handleCreate}
							type="button"
						>
							<span class="text-xs">Create "{normalizedCandidate}"</span>
							<span class="text-[10px] text-fg-muted uppercase tracking-wider">New</span>
						</button>
					{/if}

					{#each filteredNamespaces as name (name)}
						<button
							class="flex w-full cursor-pointer items-center justify-between border-l-2 border-transparent px-2 py-1.5 text-left hover:bg-hover transition-colors"
							class:border-l-accent-primary={name === selected}
							class:bg-accent-bg={name === selected}
							class:text-fg-primary={name === selected}
							class:text-fg-secondary={name !== selected}
							onclick={() => handleSelect(name)}
							type="button"
						>
							<span class="truncate text-sm font-medium">{name}</span>
						</button>
					{/each}
				{/if}
			</div>
		</div>
	</div>
{/if}
