<script lang="ts">
	import { Debounced } from 'runed';
	import { createQuery } from '@tanstack/svelte-query';
	import { listNamespaces } from '$lib/api/namespaces';
	import { normalizeNamespace } from '$lib/utils/namespace';
	import { css, cx, input } from '$lib/styles/panda';

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
		class={css({
			position: 'fixed',
			inset: '0',
			zIndex: 'popover',
			backgroundColor: 'transparent'
		})}
		onclick={handleClose}
		onkeydown={handleBackdropKeydown}
		role="button"
		tabindex="0"
		aria-label="Close namespace menu"
	></div>
	<div
		class={css({
			position: 'fixed',
			zIndex: 'overlay',
			display: 'flex',
			flexDirection: 'column',
			borderWidth: '1',
			backgroundColor: 'bg.primary',
			boxShadow: 'drag',
			outline: 'none',
			maxHeight: '60vh'
		})}
		role="dialog"
		aria-modal="false"
		aria-labelledby="namespace-picker-search"
		tabindex="-1"
		use:portal={popoverRect}
		onclick={(e) => e.stopPropagation()}
		onkeydown={(e) => e.stopPropagation()}
	>
		<div class={css({ display: 'flex', flexDirection: 'column', gap: '2', padding: '2' })}>
			<input
				id="namespace-picker-search"
				class={cx(
					input(),
					css({
						paddingX: '2',
						paddingY: '1.5',
						fontSize: 'sm',
						_focus: { borderColor: 'accent.primary' }
					})
				)}
				type="text"
				bind:this={searchInput}
				bind:value={searchQuery}
				placeholder="Search namespaces..."
				aria-label="Search namespaces"
				autocomplete="off"
			/>

			<div
				class={css({
					display: 'flex',
					maxHeight: 'list',
					flexDirection: 'column',
					overflowY: 'auto'
				})}
			>
				{#if namespacesQuery.isLoading}
					<div class={css({ padding: '2', fontSize: 'xs', color: 'fg.muted' })}>Loading...</div>
				{:else if namespacesQuery.isError}
					<div class={css({ padding: '2', fontSize: 'xs', color: 'error' })}>
						Error loading namespaces
					</div>
				{:else if filteredNamespaces.length === 0 && !canCreate}
					<div class={css({ padding: '2', fontSize: 'xs', color: 'fg.muted' })}>No results</div>
				{:else}
					{#if canCreate}
						<button
							class={css({
								display: 'flex',
								width: '100%',
								cursor: 'pointer',
								alignItems: 'center',
								justifyContent: 'space-between',
								borderBottomWidth: '1',
								paddingX: '2',
								paddingY: '1.5',
								textAlign: 'left',
								color: 'fg.secondary',
								transitionProperty: 'color, background-color',
								transitionDuration: '150ms',
								_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' }
							})}
							onclick={handleCreate}
							type="button"
						>
							<span class={css({ fontSize: 'xs' })}>Create "{normalizedCandidate}"</span>
							<span
								class={css({
									fontSize: '2xs',
									color: 'fg.muted',
									textTransform: 'uppercase',
									letterSpacing: 'wider'
								})}
							>
								New
							</span>
						</button>
					{/if}

					{#each filteredNamespaces as name (name)}
						<button
							class={css({
								display: 'flex',
								width: '100%',
								cursor: 'pointer',
								alignItems: 'center',
								justifyContent: 'space-between',
								borderLeftWidth: '2',
								borderLeftColor: name === selected ? 'accent.primary' : 'transparent',
								backgroundColor: name === selected ? 'accent.bg' : 'transparent',
								color: name === selected ? 'fg.primary' : 'fg.secondary',
								paddingX: '2',
								paddingY: '1.5',
								textAlign: 'left',
								transitionProperty: 'background-color',
								transitionDuration: '150ms',
								_hover: { backgroundColor: 'bg.hover' }
							})}
							onclick={() => handleSelect(name)}
							type="button"
						>
							<span
								class={css({
									overflow: 'hidden',
									textOverflow: 'ellipsis',
									whiteSpace: 'nowrap',
									fontSize: 'sm',
									fontWeight: 'medium'
								})}
							>
								{name}
							</span>
						</button>
					{/each}
				{/if}
			</div>
		</div>
	</div>
{/if}
