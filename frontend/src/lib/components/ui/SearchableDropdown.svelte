<script lang="ts">
	import { Debounced } from 'runed';
	import { SvelteSet } from 'svelte/reactivity';
	import { ChevronDown } from 'lucide-svelte';

	import type { Snippet } from 'svelte';

	type Action<T = unknown> = (node: HTMLElement, value: T) => {
		update?: (value: T) => void;
		destroy?: () => void;
	};

	interface OptionBase {
		id: string;
		label: string;
		searchText?: string[];
	}

	interface OptionRenderPayload {
		option: OptionBase;
		selected: boolean;
		onSelect: () => void;
	}

	interface TriggerRenderPayload {
		open: boolean;
		selectedCount: number;
		selectedOption: OptionBase | undefined;
		displayLabel: string;
		disabled: boolean;
		onOpen: () => void;
		triggerAction: Action<unknown>;
	}

	interface MenuActionValue {
		left: number;
		top: number;
		width: number;
	}

	interface Props {
		options: OptionBase[];
		value: string | string[];
		onChange: (value: string | string[]) => void;
		placeholder?: string;
		searchPlaceholder?: string;
		mode?: 'single' | 'multi';
		showSelectAll?: boolean;
		showSelectedList?: boolean;
		filter?: (option: OptionBase, query: string) => boolean;
		menuClass?: string;
		containerClass?: string;
		triggerClass?: string;
		inputClass?: string;
		triggerType?: 'button' | 'input';
		disabled?: boolean;
		searchDelay?: number;
		emptyLabel?: string;
		listAriaLabel?: string;
		renderOption: Snippet<[OptionRenderPayload]>;
		renderTrigger?: Snippet<[TriggerRenderPayload]>;
		menuAction?: Action<MenuActionValue>;
		menuActionValue?: MenuActionValue;
		searchValue?: string;
		closeOnOutside?: boolean;
		onOpen?: (trigger: HTMLButtonElement | HTMLInputElement | undefined) => void;
		onClose?: () => void;
	}

	let {
		options,
		value = $bindable(),
		onChange,
		renderOption,
		placeholder = 'Select...',
		searchPlaceholder = 'Search...',
		mode = 'single',
		showSelectAll = false,
		showSelectedList = false,
		filter,
		menuClass = '',
		containerClass = '',
		triggerClass = '',
		inputClass = '',
		triggerType = 'button',
		disabled = false,
		searchDelay = 120,
		emptyLabel = 'No results',
		listAriaLabel = 'Options',
		menuAction,
		menuActionValue = { left: 0, top: 0, width: 0 },
		searchValue = $bindable(''),
		closeOnOutside = true,
		onOpen,
		onClose,
		renderTrigger
	}: Props = $props();

	const noopAction: Action<MenuActionValue> = () => ({
		update: () => undefined,
		destroy: () => undefined
	});

	const resolvedMenuAction = $derived(menuAction ?? noopAction);

	let menuOpen = $state(false);
	let menuRef = $state<HTMLElement>();
	let menuContainerRef = $state<HTMLElement>();
	let triggerRef = $state<HTMLButtonElement | HTMLInputElement>();
	let searchInputRef = $state<HTMLInputElement>();

	const debouncedSearch = $derived(new Debounced(() => searchValue, searchDelay));

	const selectedSet = $derived(
		new SvelteSet(Array.isArray(value) ? value : value ? [value] : [])
	);
	const selectedCount = $derived(selectedSet.size);

	const filteredOptions = $derived.by(() => {
		const query = debouncedSearch.current.trim().toLowerCase();
		if (!query) return options;
		if (filter) {
			return options.filter((option) => filter(option, query));
		}
		return options.filter((option) => {
			const base = [option.label];
			const extra = option.searchText ?? [];
			return [...base, ...extra].some((text) => text.toLowerCase().includes(query));
		});
	});

	function updateValue(next: string | string[]) {
		onChange(next);
	}

	function handleSelect(id: string) {
		if (mode === 'single') {
			updateValue(id);
			menuOpen = false;
			searchValue = '';
			onClose?.();
			return;
		}
		const current = new SvelteSet(selectedSet);
		if (current.has(id)) {
			current.delete(id);
		} else {
			current.add(id);
		}
		updateValue(Array.from(current));
	}

	function selectAll() {
		if (mode !== 'multi') return;
		updateValue(filteredOptions.map((option) => option.id));
	}

	function deselectAll() {
		if (mode !== 'multi') return;
		updateValue([]);
	}

	function openMenu() {
		if (disabled) return;
		menuOpen = true;
		onOpen?.(triggerRef);
		if (triggerType === 'button') {
			setTimeout(() => searchInputRef?.focus(), 0);
		}
	}

	function closeMenu() {
		menuOpen = false;
		searchValue = '';
		onClose?.();
	}

	function isSelected(id: string) {
		return selectedSet.has(id);
	}

	const displayLabel = $derived.by(() => {
		if (mode === 'multi') {
			if (selectedCount === 0) return placeholder;
			return `${selectedCount} selected`;
		}
		const selectedOption = options.find((option) => option.id === value);
		return selectedOption ? selectedOption.label : placeholder;
	});

	const setTriggerRef: Action<unknown> = (node) => {
		triggerRef = node as HTMLButtonElement | HTMLInputElement;
		return {
			destroy: () => {
				if (triggerRef === node) {
					triggerRef = undefined;
				}
			}
		};
	};

	const triggerPayload = $derived.by(() => ({
		open: menuOpen,
		selectedCount,
		selectedOption: options.find((option) => option.id === value),
		displayLabel,
		disabled,
		onOpen: openMenu,
		triggerAction: setTriggerRef
	}));

	// DOM: $derived can't detect outside clicks.
	$effect(() => {
		if (!menuOpen) return;
		if (!closeOnOutside) return;
		const handleOutside = (event: MouseEvent) => {
			const target = event.target as Node | null;
			if (!target) return;
			if (menuRef?.contains(target)) return;
			if (menuContainerRef?.contains(target)) return;
			if (triggerRef?.contains(target)) return;
			closeMenu();
		};
		window.addEventListener('mousedown', handleOutside, true);
		return () => {
			window.removeEventListener('mousedown', handleOutside, true);
		};
	});
</script>

<div class={`column-select ${containerClass}`.trim()} bind:this={menuRef}>
	{#if triggerType === 'input'}
		<input
			type="text"
			class={inputClass}
			bind:value={searchValue}
			placeholder={placeholder}
			onfocus={openMenu}
			aria-haspopup="listbox"
			use:setTriggerRef={undefined}
			{disabled}
		/>
	{:else if renderTrigger}
		{@render renderTrigger(triggerPayload)}
	{:else}
		<button
			type="button"
			class={`column-trigger ${triggerClass}`.trim()}
			onclick={openMenu}
			aria-expanded={menuOpen}
			use:setTriggerRef={undefined}
			{disabled}
		>
			<span class={selectedCount > 0 ? 'column-label' : 'column-placeholder'}>{displayLabel}</span>
			<ChevronDown size={14} class="chevron" />
		</button>
	{/if}
	{#if menuOpen}
		<div
			class={`column-menu ${menuClass}`.trim()}
			role="listbox"
			aria-multiselectable={mode === 'multi'}
			aria-label={listAriaLabel}
			use:resolvedMenuAction={menuActionValue}
			bind:this={menuContainerRef}
		>
			{#if triggerType === 'button'}
				<div class="column-search">
					<input
						bind:this={searchInputRef}
						bind:value={searchValue}
						type="text"
						placeholder={searchPlaceholder}
						class="column-search-input"
					/>
				</div>
			{/if}
			{#if mode === 'multi' && showSelectAll}
				<div class="flex gap-2 border-b p-2 bg-secondary border-tertiary">
					<button
						type="button"
						class="select-action-btn flex-1 cursor-pointer border bg-transparent px-2 py-1 text-xs border-tertiary text-fg-secondary"
						onclick={(event) => {
							event.stopPropagation();
							selectAll();
						}}
					>
						Select All {searchValue ? 'Filtered' : ''}
					</button>
					<button
						type="button"
						class="select-action-btn flex-1 cursor-pointer border bg-transparent px-2 py-1 text-xs border-tertiary text-fg-secondary"
						onclick={(event) => {
							event.stopPropagation();
							deselectAll();
						}}
					>
						Clear
					</button>
				</div>
			{/if}
			<div class="column-options">
				{#if filteredOptions.length === 0}
					<div class="no-results">{emptyLabel}</div>
				{:else}
					{#each filteredOptions as option (option.id)}
					{@render renderOption({
						option,
						selected: isSelected(option.id),
						onSelect: () => handleSelect(option.id)
					})}
					{/each}
				{/if}
			</div>
		</div>
	{/if}
</div>

{#if showSelectedList && mode === 'multi' && Array.isArray(value) && value.length > 0}
	<div class="column-selected-list mt-2 max-h-15 overflow-y-auto border p-2 text-xs select-mono">
		{value.join(', ')}
	</div>
{/if}
