<script lang="ts">
	import { ChevronDown, Plus } from 'lucide-svelte';

	interface Props {
		branches: string[];
		value: string;
		placeholder?: string;
		allowCreate?: boolean;
		onChange: (value: string) => void;
	}

	let {
		branches,
		value = $bindable(),
		placeholder = 'Select branch',
		allowCreate = false,
		onChange
	}: Props = $props();

	let menuOpen = $state(false);
	let menuRef = $state<HTMLElement>();
	let triggerRef = $state<HTMLButtonElement>();
	let searchQuery = $state('');
	let searchInputRef = $state<HTMLInputElement>();
	let popoverRect = $state({ left: 0, top: 0, width: 240 });

	const normalizedBranches = $derived(branches.length ? branches : ['master']);
	const filteredBranches = $derived(
		searchQuery
			? normalizedBranches.filter((branch) =>
					branch.toLowerCase().includes(searchQuery.toLowerCase())
				)
			: normalizedBranches
	);
	const trimmedSearch = $derived(searchQuery.trim());
	const canCreate = $derived(
		allowCreate &&
			trimmedSearch.length > 0 &&
			!normalizedBranches.some((branch) => branch === trimmedSearch)
	);
	const currentValue = $derived(value || 'master');

	function selectBranch(branch: string) {
		onChange(branch);
		menuOpen = false;
		searchQuery = '';
	}

	function openMenu() {
		menuOpen = true;
		updatePopoverPosition();
		setTimeout(() => searchInputRef?.focus(), 0);
	}

	function updatePopoverPosition() {
		const trigger = triggerRef;
		if (!trigger) return;
		const rect = trigger.getBoundingClientRect();
		const width = Math.max(rect.width, 180);
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
		node.style.setProperty('--popover-left', `${rect.left}px`);
		node.style.setProperty('--popover-top', `${rect.top}px`);
		node.style.setProperty('--popover-width', `${rect.width}px`);
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

	$effect(() => {
		if (!menuOpen) return;
		const handleOutside = (event: MouseEvent) => {
			const target = event.target as Node | null;
			if (!target) return;
			if (menuRef?.contains(target)) return;
			if (triggerRef?.contains(target)) return;
			menuOpen = false;
			searchQuery = '';
		};
		const handleResize = () => updatePopoverPosition();
		window.addEventListener('mousedown', handleOutside, true);
		window.addEventListener('resize', handleResize);
		window.addEventListener('scroll', handleResize, true);
		return () => {
			window.removeEventListener('mousedown', handleOutside, true);
			window.removeEventListener('resize', handleResize);
			window.removeEventListener('scroll', handleResize, true);
		};
	});
</script>

<div class="column-select" bind:this={menuRef}>
	<button
		type="button"
		class="column-trigger"
		onclick={openMenu}
		aria-expanded={menuOpen}
		bind:this={triggerRef}
	>
		{#if currentValue}
			<span class="column-label">{currentValue}</span>
		{:else}
			<span class="column-placeholder">{placeholder}</span>
		{/if}
		<ChevronDown size={14} class="chevron" />
	</button>
	{#if menuOpen}
		<div
			class="column-menu branch-picker__menu fixed z-popover"
			role="listbox"
			bind:this={menuRef}
			use:portal={popoverRect}
		>
			<div class="column-search">
				<input
					bind:this={searchInputRef}
					bind:value={searchQuery}
					type="text"
					placeholder="Search branches..."
					class="column-search-input"
					aria-label="Search branches"
				/>
			</div>
			<div class="column-options">
				{#if canCreate}
					<button
						type="button"
						class="column-option"
						onclick={() => selectBranch(trimmedSearch)}
						role="option"
						aria-selected="false"
					>
						<Plus size={12} />
						<span>Create "{trimmedSearch}"</span>
					</button>
				{/if}
				{#each filteredBranches as branch (branch)}
					<button
						type="button"
						class="column-option"
						class:selected={currentValue === branch}
						onclick={() => selectBranch(branch)}
						role="option"
						aria-selected={currentValue === branch}
					>
						<span>{branch}</span>
					</button>
				{:else}
					<div class="no-results">No branches found</div>
				{/each}
			</div>
		</div>
	{/if}
</div>
