<script lang="ts">
	import { X } from 'lucide-svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import type { DataSource } from '$lib/types/datasource';
	import type { AnalysisGalleryItem } from '$lib/types/analysis';
	import { listAnalyses } from '$lib/api/analysis';
	import FileTypeBadge from '$lib/components/common/FileTypeBadge.svelte';
	import type { SourceType } from '$lib/utils/fileTypes';
	import SearchableDropdown from '$lib/components/ui/SearchableDropdown.svelte';
	import { css, button, menuItem, cx } from '$lib/styles/panda';

	interface PickerOption {
		id: string;
		label: string;
		kind: 'datasource' | 'analysis';
		payload: DataSource | AnalysisGalleryItem;
		searchText?: string[];
	}

	interface Props {
		datasources: DataSource[];
		selected: string | string[];
		mode?: 'single' | 'multi';
		placeholder?: string;
		label?: string;
		id?: string;
		showChips?: boolean;
		showBulkActions?: boolean;
		excludeIds?: string[];
		highlightId?: string;
		searchFields?: ('name' | 'source_type' | 'file_type')[];
		modeSource?: 'datasource' | 'analysis';
		onSelect?: (id: string, name: string) => void;
		onDeselect?: (id: string) => void;
	}

	let {
		datasources,
		selected = $bindable(),
		mode = 'single',
		placeholder = 'Search datasources...',
		label,
		id: _id,
		showChips = true,
		showBulkActions = true,
		excludeIds = [],
		highlightId,
		searchFields = ['name', 'source_type'],
		modeSource = 'datasource',
		onSelect,
		onDeselect
	}: Props = $props();

	let searchValue = $state('');

	const excludedSet = $derived(new SvelteSet(excludeIds));

	const availableOptions = $derived(datasources.filter((ds) => !excludedSet.has(ds.id)));

	const selectedDatasources = $derived.by(() => {
		if (modeSource !== 'datasource') return [];
		if (mode === 'single') {
			const s = selected as string | undefined;
			return s ? datasources.filter((ds) => ds.id === s) : [];
		}
		const arr = selected as string[] | undefined;
		if (!arr?.length) return [];
		const set = new SvelteSet(arr);
		return datasources.filter((ds) => set.has(ds.id));
	});

	let analyses = $state<AnalysisGalleryItem[]>([]);
	let analysesLoaded = $state(false);

	// Network: $derived can't fetch analyses.
	$effect(() => {
		if (modeSource !== 'analysis') return;
		if (analysesLoaded) return;
		listAnalyses()
			.map((value) => {
				analyses = value;
				analysesLoaded = true;
			})
			.mapErr(() => {
				analyses = [];
				analysesLoaded = true;
			});
	});

	const options = $derived.by(() => {
		if (modeSource === 'analysis') {
			return analyses.map(
				(analysis) =>
					({
						id: analysis.id,
						label: analysis.name,
						kind: 'analysis',
						payload: analysis,
						searchText: [analysis.name]
					}) satisfies PickerOption
			);
		}
		return availableOptions.map((ds) => {
			const fileType = (ds.config?.file_type as string) ?? '';
			const searchText = [
				ds.name,
				searchFields.includes('source_type') ? ds.source_type : '',
				searchFields.includes('file_type') ? fileType : ''
			].filter(Boolean);
			return {
				id: ds.id,
				label: ds.name,
				kind: 'datasource',
				payload: ds,
				searchText
			} satisfies PickerOption;
		});
	});

	const canSelectAll = $derived(
		mode === 'multi' && modeSource === 'datasource' && options.length > 0
	);

	function handleChange(next: string | string[]) {
		if (mode === 'single') {
			const id = next as string;
			const match = options.find((option) => option.id === id);
			if (!match) return;
			selected = id;
			onSelect?.(id, match.label);
			searchValue = '';
			return;
		}
		const nextIds = next as string[];
		const nextSet = new SvelteSet(nextIds);
		const prevSet = new SvelteSet((selected as string[]) ?? []);
		const added = nextIds.filter((id) => !prevSet.has(id));
		const removed = Array.from(prevSet).filter((id) => !nextSet.has(id));
		selected = nextIds;
		added.forEach((id) => {
			const match = options.find((option) => option.id === id);
			if (!match) return;
			onSelect?.(id, match.label);
		});
		removed.forEach((id) => onDeselect?.(id));
	}

	function selectAll() {
		if (!canSelectAll) return;
		const ids = options.map((option) => option.id);
		const current = new SvelteSet((selected as string[]) ?? []);
		ids.forEach((id) => current.add(id));
		const next = Array.from(current);
		handleChange(next);
	}

	function deselectAll() {
		if (!canSelectAll) return;
		const current = (selected as string[]) ?? [];
		current.forEach((id) => onDeselect?.(id));
		selected = [];
	}

	function deselect(id: string) {
		if (mode !== 'multi') return;
		const arr = (selected as string[]) ?? [];
		selected = arr.filter((value) => value !== id);
		onDeselect?.(id);
	}
</script>

<SearchableDropdown
	{options}
	value={selected}
	onChange={handleChange}
	{placeholder}
	searchPlaceholder={placeholder}
	{mode}
	showSelectAll={showBulkActions}
	showSelectedList={false}
	triggerType="input"
	inputClass={css({
		width: 'full',
		borderWidth: '1',
		backgroundColor: 'bg.primary',
		paddingX: '3',
		paddingY: '2',
		fontFamily: 'mono',
		fontSize: 'sm',
		_focus: { borderColor: 'accent.primary', outline: 'none' }
	})}
	{searchValue}
	emptyLabel="No datasources found"
	listAriaLabel={label ?? 'Available datasources'}
	{renderOption}
/>

{#if mode === 'multi' && modeSource === 'datasource' && showChips && selectedDatasources.length > 0}
	<div class={css({ marginTop: '2', display: 'flex', flexWrap: 'wrap', gap: '2' })}>
		{#each selectedDatasources as ds (ds.id)}
			<span
				class={css({
					display: 'inline-flex',
					alignItems: 'center',
					gap: '1',
					borderWidth: '1',
					borderColor: ds.id === highlightId ? 'accent.primary' : 'border.primary',
					paddingX: '2',
					paddingY: '1',
					fontSize: 'xs',
					...(ds.id === highlightId
						? { backgroundColor: 'accent.bg', color: 'accent.primary' }
						: {})
				})}
			>
				{ds.name}
				<button
					class={css({
						display: 'inline-flex',
						height: 'iconSm',
						width: 'iconSm',
						cursor: 'pointer',
						alignItems: 'center',
						justifyContent: 'center',
						borderStyle: 'none',
						backgroundColor: 'transparent',
						padding: '0',
						color: 'fg.muted',
						_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' }
					})}
					onclick={() => deselect(ds.id)}
					aria-label={`Remove ${ds.name}`}
					type="button"
				>
					<X size={12} />
				</button>
			</span>
		{/each}
	</div>
{/if}

{#if canSelectAll && showBulkActions}
	<div class={css({ marginTop: '2', display: 'flex', gap: '2' })}>
		<button class={button({ variant: 'secondary', size: 'sm' })} onclick={selectAll} type="button"
			>Select All</button
		>
		<button class={button({ variant: 'secondary', size: 'sm' })} onclick={deselectAll} type="button"
			>Deselect All</button
		>
	</div>
{/if}

{#snippet renderOption(payload: {
	option: { id: string; label: string };
	selected: boolean;
	onSelect: () => void;
})}
	{@const option = payload.option as PickerOption}
	<button
		class={cx(
			menuItem(),
			css({
				display: 'flex',
				justifyContent: 'space-between',
				fontFamily: 'mono',
				fontSize: 'sm',
				...(payload.selected ? { backgroundColor: 'accent.bg' } : {}),
				...(option.id === highlightId
					? { borderLeftWidth: '3', borderLeftColor: 'accent.secondary' }
					: {})
			})
		)}
		onclick={payload.onSelect}
		role="option"
		aria-selected={payload.selected}
		type="button"
	>
		<span
			class={css({ flex: '1', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' })}
			>{option.label}</span
		>
		{#if option.kind === 'datasource'}
			{@const ds = option.payload as DataSource}
			{#if ds.id === highlightId}
				<span
					class={css({
						marginLeft: '2',
						borderWidth: '1',
						borderColor: 'accent.primary',
						backgroundColor: 'accent.bg',
						paddingX: '2',
						paddingY: '1',
						fontSize: 'xs',
						color: 'accent.primary'
					})}>current</span
				>
			{:else if ds.source_type === 'file'}
				<FileTypeBadge path={(ds.config?.file_path as string) ?? ''} size="sm" showIcon={false} />
			{:else}
				{@const badgeSource = ds.source_type as SourceType}
				<FileTypeBadge sourceType={badgeSource} size="sm" showIcon={false} />
			{/if}
		{:else}
			<span
				class={css({
					marginLeft: '2',
					borderWidth: '1',
					backgroundColor: 'bg.tertiary',
					paddingX: '2',
					paddingY: '1',
					fontSize: 'xs',
					color: 'fg.muted'
				})}>analysis</span
			>
		{/if}
	</button>
{/snippet}
