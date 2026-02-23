<script lang="ts">
	import { ChevronDown, Plus } from 'lucide-svelte';
	import SearchableDropdown from '$lib/components/ui/SearchableDropdown.svelte';

	interface BranchOption {
		id: string;
		label: string;
		kind: 'branch' | 'create';
	}

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

	let searchValue = $state('');
	let menuOpen = $state(false);
	let popoverRect = $state({ left: 0, top: 0, width: 240 });

	const normalizedBranches = $derived(branches.length ? branches : ['master']);
	const trimmedSearch = $derived(searchValue.trim());
	const canCreate = $derived(
		allowCreate &&
			trimmedSearch.length > 0 &&
			!normalizedBranches.some((branch) => branch === trimmedSearch)
	);
	const currentValue = $derived(value || 'master');
	const options = $derived.by(() => {
		const base = normalizedBranches.map((branch) => ({
			id: branch,
			label: branch,
			kind: 'branch'
		}) satisfies BranchOption);
		if (!canCreate) return base;
		return [
			{
				id: `__create__${trimmedSearch}`,
				label: `Create "${trimmedSearch}"`,
				kind: 'create'
			} satisfies BranchOption,
			...base
		];
	});

	let lastTrigger = $state<HTMLElement | null>(null);

	function updatePopoverPosition(trigger?: HTMLElement | null) {
		const node = trigger;
		if (!node) return;
		const rect = node.getBoundingClientRect();
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

	function handleChange(next: string | string[]) {
		const id = next as string;
		const match = options.find((option) => option.id === id);
		if (!match) return;
		if (match.kind === 'create') {
			onChange(trimmedSearch);
			searchValue = '';
			return;
		}
		onChange(match.label);
		searchValue = '';
	}

	function handleOpen(trigger?: HTMLButtonElement | HTMLInputElement) {
		menuOpen = true;
		lastTrigger = trigger ?? null;
		updatePopoverPosition(trigger ?? null);
	}

	function handleClose() {
		menuOpen = false;
		searchValue = '';
	}

	// DOM: $derived can't track resize/scroll.
	$effect(() => {
		if (!menuOpen) return;
		const handleResize = () => updatePopoverPosition(lastTrigger);
		window.addEventListener('resize', handleResize);
		window.addEventListener('scroll', handleResize, true);
		return () => {
			window.removeEventListener('resize', handleResize);
			window.removeEventListener('scroll', handleResize, true);
		};
	});
</script>

<SearchableDropdown
	options={options}
	value={currentValue}
	onChange={handleChange}
	placeholder={placeholder}
	searchPlaceholder="Search branches..."
	menuClass="branch-picker__menu fixed z-popover"
	menuAction={portal}
	menuActionValue={popoverRect}
	searchValue={searchValue}
	onOpen={handleOpen}
	onClose={handleClose}
	renderTrigger={renderTrigger}
	renderOption={renderOption}
/>

{#snippet renderTrigger(payload: { open: boolean; selectedCount: number; selectedOption: unknown; displayLabel: string; disabled: boolean; onOpen: () => void; triggerAction: (node: HTMLElement, value: unknown) => { update?: (value: unknown) => void; destroy?: () => void } })}
	<button
		type="button"
		class="column-trigger"
		onclick={payload.onOpen}
		aria-expanded={payload.open}
		use:payload.triggerAction={undefined}
	>
		{#if currentValue}
			<span class="column-label">{currentValue}</span>
		{:else}
			<span class="column-placeholder">{placeholder}</span>
		{/if}
		<ChevronDown size={14} class="chevron" />
	</button>
{/snippet}

{#snippet renderOption(payload: { option: { id: string; label: string }; selected: boolean; onSelect: () => void })}
	{@const option = payload.option as BranchOption}
	<button
		type="button"
		class="column-option"
		class:selected={payload.selected}
		onclick={payload.onSelect}
		role="option"
		aria-selected={payload.selected}
	>
		{#if option.kind === 'create'}
			<Plus size={12} />
		{/if}
		<span>{option.label}</span>
	</button>
{/snippet}
