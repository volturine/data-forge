<script lang="ts">
	import { X } from 'lucide-svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import type { DataSource } from '$lib/types/datasource';
	import type { AnalysisGalleryItem } from '$lib/types/analysis';
	import { listAnalyses } from '$lib/api/analysis';
	import FileTypeBadge from '$lib/components/common/FileTypeBadge.svelte';
	import type { SourceType } from '$lib/utils/fileTypes';

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
		id,
		showChips = true,
		showBulkActions = true,
		excludeIds = [],
		highlightId,
		searchFields = ['name', 'source_type'],
		modeSource = 'datasource',
		onSelect,
		onDeselect
	}: Props = $props();

	let search = $state('');
	let showPicker = $state(false);
	let blurTimeout = $state<ReturnType<typeof setTimeout> | null>(null);

	const selectedSet = $derived(() => {
		if (mode === 'single') {
			return selected ? new SvelteSet([selected as string]) : new SvelteSet<string>();
		}
		return new SvelteSet((selected as string[]) ?? []);
	});

	const excludedSet = $derived(new SvelteSet(excludeIds));

	const availableOptions = $derived(datasources.filter((ds) => !excludedSet.has(ds.id)));

	const filteredOptions = $derived(() => {
		if (modeSource === 'analysis') {
			if (!search.trim()) return analyses;
			const query = search.toLowerCase();
			return analyses.filter((analysis) => analysis.name.toLowerCase().includes(query));
		}
		if (!search.trim()) return availableOptions;

		const query = search.toLowerCase();
		return availableOptions.filter((ds) => {
			const matchesName = searchFields.includes('name') && ds.name.toLowerCase().includes(query);
			const matchesSourceType =
				searchFields.includes('source_type') && ds.source_type.toLowerCase().includes(query);
			const fileType = (ds.config?.file_type as string) ?? '';
			const matchesFileType =
				searchFields.includes('file_type') && fileType.toLowerCase().includes(query);
			return matchesName || matchesSourceType || matchesFileType;
		});
	});

	const selectedDatasources = $derived(() => {
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

	function handleFocus() {
		if (blurTimeout) {
			clearTimeout(blurTimeout);
			blurTimeout = null;
		}
		showPicker = true;
	}

	function handleBlur() {
		blurTimeout = setTimeout(() => {
			showPicker = false;
		}, 100);
	}

	function toggle(id: string, name: string) {
		if (mode === 'single') {
			selected = id;
			onSelect?.(id, name);
			showPicker = false;
			search = '';
		} else {
			const arr = (selected as string[]) ?? [];
			const set = new SvelteSet(arr);
			if (set.has(id)) {
				set.delete(id);
				onDeselect?.(id);
			} else {
				set.add(id);
				onSelect?.(id, name);
			}
			selected = Array.from(set);
		}
	}

	function selectAll() {
		if (mode !== 'multi' || modeSource !== 'datasource') return;
		const filtered = filteredOptions();
		const filteredIds = filtered.map((ds) => ds.id);
		const current = new SvelteSet((selected as string[]) ?? []);
		filteredIds.forEach((id) => current.add(id));
		selected = Array.from(current);
		filtered.forEach((ds) => {
			if (!selectedSet().has(ds.id)) {
				onSelect?.(ds.id, ds.name);
			}
		});
	}

	function deselectAll() {
		if (mode !== 'multi' || modeSource !== 'datasource') return;
		const current = (selected as string[]) ?? [];
		current.forEach((id) => onDeselect?.(id));
		selected = [];
	}

	function deselect(id: string) {
		if (mode !== 'multi') return;
		const arr = (selected as string[]) ?? [];
		selected = arr.filter((x) => x !== id);
		onDeselect?.(id);
	}

	function isSelected(id: string): boolean {
		return selectedSet().has(id);
	}

	const inputId = $derived(id ? `${id}-datasource-search` : undefined);
	const listboxId = $derived(id ? `${id}-datasource-listbox` : 'datasource-listbox');
</script>

<div class="relative w-full">
	<input
		type="text"
		class="w-full border border-tertiary bg-primary px-3 py-2 font-mono text-sm text-fg-primary focus:border-accent-primary focus:outline-none"
		bind:value={search}
		onfocus={handleFocus}
		onblur={handleBlur}
		{placeholder}
		aria-label={label}
		aria-haspopup="listbox"
		aria-expanded={showPicker}
		id={inputId}
		role="combobox"
		aria-controls={listboxId}
	/>

	{#if showPicker}
		<div
			class="absolute left-0 right-0 top-full z-50 mt-1 max-h-50 overflow-y-auto border border-tertiary bg-primary"
			role="listbox"
			id={listboxId}
			aria-label="Available datasources"
		>
			{#if filteredOptions().length === 0}
				<div class="p-4 text-center text-sm text-fg-muted">No datasources found</div>
			{:else}
				{#each filteredOptions() as item (item.id)}
					<button
						class="picker-option flex w-full cursor-pointer items-center justify-between border-b border-tertiary bg-transparent px-3 py-2 font-mono text-left text-sm text-fg-primary last:border-b-0 hover:bg-bg-hover"
						class:selected={isSelected(item.id)}
						class:highlighted={item.id === highlightId}
						onmousedown={(e) => {
							e.preventDefault();
							toggle(item.id, item.name);
						}}
						role="option"
						aria-selected={isSelected(item.id)}
						type="button"
					>
						<span class="flex-1 overflow-hidden text-ellipsis whitespace-nowrap">{item.name}</span>
						{#if modeSource === 'datasource'}
							{@const ds = item as DataSource}
							{#if ds.id === highlightId}
								<span
									class="ml-2 border border-accent-primary bg-accent-bg px-2 py-1 text-xs text-accent-primary"
									>current</span
								>
							{:else if ds.source_type === 'file'}
								<FileTypeBadge
									path={(ds.config?.file_path as string) ?? ''}
									size="sm"
									showIcon={false}
								/>
							{:else}
								{@const badgeSource = ds.source_type as SourceType}
								<FileTypeBadge sourceType={badgeSource} size="sm" showIcon={false} />
							{/if}
						{:else}
							<span class="ml-2 border border-tertiary bg-tertiary px-2 py-1 text-xs text-fg-muted"
								>analysis</span
							>
						{/if}
					</button>
				{/each}
			{/if}
		</div>
	{/if}

	{#if mode === 'multi' && modeSource === 'datasource' && showChips && selectedDatasources().length > 0}
		<div class="mt-2 flex flex-wrap gap-2">
			{#each selectedDatasources() as ds (ds.id)}
				<span
					class="chip inline-flex items-center gap-1 border border-tertiary bg-badge-bg px-2 py-1 text-xs text-badge-fg"
					class:highlighted={ds.id === highlightId}
				>
					{ds.name}
					<button
						class="chip-remove inline-flex h-4 w-4 cursor-pointer items-center justify-center border-none bg-transparent p-0 text-fg-muted hover:bg-bg-hover hover:text-fg-primary"
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

	{#if mode === 'multi' && modeSource === 'datasource' && showBulkActions && filteredOptions().length > 0}
		<div class="mt-2 flex gap-2">
			<button class="btn-secondary btn-sm" onclick={selectAll} type="button">Select All</button>
			<button class="btn-secondary btn-sm" onclick={deselectAll} type="button">Deselect All</button>
		</div>
	{/if}
</div>
