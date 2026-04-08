<script lang="ts">
	import { Debounced } from 'runed';
	import { SvelteSet } from 'svelte/reactivity';
	import { ChevronDown } from 'lucide-svelte';
	import { css, cx, emptyText, input } from '$lib/styles/panda';

	import type { Snippet } from 'svelte';

	type Action<T = unknown> = (
		node: HTMLElement,
		value: T
	) => {
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
		clearable?: boolean;
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
		clearable = false,
		onOpen,
		onClose,
		renderTrigger
	}: Props = $props();

	const uid = `sd-${Math.random().toString(36).slice(2, 7)}`;

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

	const selectedSet = $derived(new SvelteSet(Array.isArray(value) ? value : value ? [value] : []));
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

	const triggerPayload = $derived({
		open: menuOpen,
		selectedCount,
		selectedOption: options.find((option) => option.id === value),
		displayLabel,
		disabled,
		onOpen: openMenu,
		triggerAction: setTriggerRef
	});

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

<div
	class={cx(
		css({
			position: 'relative',
			display: 'flex',
			flexDirection: 'column',
			gap: '2',
			minWidth: 'inputSm'
		}),
		containerClass
	)}
	bind:this={menuRef}
>
	{#if triggerType === 'input'}
		<input
			type="text"
			class={inputClass}
			id="{uid}-trigger"
			aria-label="Search"
			bind:value={searchValue}
			{placeholder}
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
			class={cx(
				css({
					display: 'flex',
					alignItems: 'center',
					gap: '2',
					paddingX: '3',
					paddingY: '2.5',
					borderWidth: '1',
					backgroundColor: 'bg.secondary',
					cursor: 'pointer',
					justifyContent: 'space-between',
					fontSize: 'sm',
					_focusVisible: {
						outline: '2px solid {colors.accent.secondary}',
						outlineOffset: 'px'
					}
				}),
				triggerClass
			)}
			onclick={openMenu}
			aria-expanded={menuOpen}
			use:setTriggerRef={undefined}
			{disabled}
		>
			<span
				class={selectedCount > 0
					? css({
							flex: '1',
							textAlign: 'left',
							minWidth: '0',
							overflow: 'hidden',
							textOverflow: 'ellipsis',
							whiteSpace: 'nowrap'
						})
					: css({ color: 'fg.muted' })}>{displayLabel}</span
			>
			{#if clearable && selectedCount > 0}
				<span
					role="button"
					tabindex="0"
					class={css({
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'center',
						width: 'iconSm',
						height: 'iconSm',
						flexShrink: '0',
						color: 'fg.muted',
						fontSize: '2xs',
						lineHeight: 'none',
						cursor: 'pointer',
						_hover: { color: 'fg.primary', backgroundColor: 'bg.tertiary' }
					})}
					onclick={(e) => {
						e.stopPropagation();
						updateValue(mode === 'multi' ? [] : '');
						onClose?.();
					}}
					onkeydown={(e) => {
						if (e.key === 'Enter' || e.key === ' ') {
							e.stopPropagation();
							updateValue(mode === 'multi' ? [] : '');
							onClose?.();
						}
					}}
					aria-label="Clear selection">✕</span
				>
			{:else}
				<ChevronDown size={14} class={css({ color: 'fg.muted' })} />
			{/if}
		</button>
	{/if}
	{#if menuOpen}
		<div
			class={cx(
				css({
					position: 'absolute',
					zIndex: 'dropdown',
					left: '0',
					minWidth: '100%',
					width: '100%',
					maxWidth: '100%',
					backgroundColor: 'bg.primary',
					borderWidth: '1',
					padding: '2',
					display: 'flex',
					flexDirection: 'column',
					gap: '2'
				}),
				menuClass
			)}
			role="listbox"
			aria-multiselectable={mode === 'multi'}
			aria-label={listAriaLabel}
			use:resolvedMenuAction={menuActionValue}
			bind:this={menuContainerRef}
		>
			{#if triggerType === 'button'}
				<div class={css({ paddingX: '2', paddingY: '0' })}>
					<input
						bind:this={searchInputRef}
						id="{uid}-menu-search"
						aria-label="Search"
						bind:value={searchValue}
						type="text"
						placeholder={searchPlaceholder}
						class={input({ variant: 'menu' })}
					/>
				</div>
			{/if}
			{#if mode === 'multi' && showSelectAll}
				<div
					class={css({
						display: 'flex',
						gap: '2',
						borderBottomWidth: '1',
						padding: '2',
						backgroundColor: 'bg.secondary'
					})}
				>
					<button
						type="button"
						class={css({
							flex: '1',
							cursor: 'pointer',
							borderWidth: '1',
							backgroundColor: 'transparent',
							paddingX: '2',
							paddingY: '1',
							fontSize: 'xs',
							color: 'fg.secondary',
							_hover: {
								backgroundColor: 'bg.hover',
								color: 'accent.secondary'
							}
						})}
						onclick={(event) => {
							event.stopPropagation();
							selectAll();
						}}
					>
						Select All {searchValue ? 'Filtered' : ''}
					</button>
					<button
						type="button"
						class={css({
							flex: '1',
							cursor: 'pointer',
							borderWidth: '1',
							backgroundColor: 'transparent',
							paddingX: '2',
							paddingY: '1',
							fontSize: 'xs',
							color: 'fg.secondary',
							_hover: {
								backgroundColor: 'bg.hover',
								color: 'accent.secondary'
							}
						})}
						onclick={(event) => {
							event.stopPropagation();
							deselectAll();
						}}
					>
						Clear
					</button>
				</div>
			{/if}
			<div
				class={css({
					display: 'flex',
					flexDirection: 'column',
					gap: '2',
					maxHeight: 'dropdown',
					overflowY: 'auto',
					overflowX: 'hidden',
					padding: '2',
					scrollbarWidth: 'thin',
					scrollbarColor: '{colors.border.primary} transparent'
				})}
			>
				{#if filteredOptions.length === 0}
					<div class={emptyText({ size: 'panel' })}>
						{emptyLabel}
					</div>
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
			{#if mode === 'multi'}
				<button
					type="button"
					class={css({
						width: '100%',
						cursor: 'pointer',
						borderWidth: '1',
						backgroundColor: 'accent.primary',
						color: 'fg.inverse',
						paddingX: '3',
						paddingY: '1.5',
						fontSize: 'sm',
						fontWeight: 'medium',
						_hover: { opacity: '0.9' }
					})}
					onclick={(e) => {
						e.stopPropagation();
						closeMenu();
					}}
				>
					Done{selectedCount > 0 ? ` (${selectedCount})` : ''}
				</button>
			{/if}
		</div>
	{/if}
</div>

{#if showSelectedList && mode === 'multi' && Array.isArray(value) && value.length > 0}
	<div
		class={cx(
			css({
				maxWidth: '100%',
				overflowWrap: 'anywhere',
				wordBreak: 'break-word',
				whiteSpace: 'normal'
			}),
			css({ fontFamily: 'mono' }),
			css({
				marginTop: '2',
				maxHeight: 'labelSm',
				overflowY: 'auto',
				borderWidth: '1',
				padding: '2',
				fontSize: 'xs'
			})
		)}
	>
		{value.join(', ')}
	</div>
{/if}
