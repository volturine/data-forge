<script lang="ts">
	import { X } from 'lucide-svelte';
	import type { DataSource } from '$lib/types/datasource';
	import FileTypeBadge from '$lib/components/common/FileTypeBadge.svelte';

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
		onSelect,
		onDeselect
	}: Props = $props();

	let search = $state('');
	let showPicker = $state(false);
	let blurTimeout = $state<ReturnType<typeof setTimeout> | null>(null);

	const selectedSet = $derived(() => {
		if (mode === 'single') {
			return selected ? new Set([selected as string]) : new Set<string>();
		}
		return new Set((selected as string[]) ?? []);
	});

	const excludedSet = $derived(new Set(excludeIds));

	const availableOptions = $derived(datasources.filter((ds) => !excludedSet.has(ds.id)));

	const filteredOptions = $derived(() => {
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
		if (mode === 'single') {
			const s = selected as string | undefined;
			return s ? datasources.filter((ds) => ds.id === s) : [];
		}
		const arr = selected as string[] | undefined;
		if (!arr?.length) return [];
		const set = new Set(arr);
		return datasources.filter((ds) => set.has(ds.id));
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
			// eslint-disable-next-line svelte/prefer-svelte-reactivity
			const set = new Set(arr);
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
		if (mode !== 'multi') return;
		const filtered = filteredOptions();
		const filteredIds = filtered.map((ds) => ds.id);
		// eslint-disable-next-line svelte/prefer-svelte-reactivity
		const current = new Set((selected as string[]) ?? []);
		filteredIds.forEach((id) => current.add(id));
		selected = Array.from(current);
		filtered.forEach((ds) => {
			if (!selectedSet().has(ds.id)) {
				onSelect?.(ds.id, ds.name);
			}
		});
	}

	function deselectAll() {
		if (mode !== 'multi') return;
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

<div
	class="datasource-picker"
	class:mode-single={mode === 'single'}
	class:mode-multi={mode === 'multi'}
>
	<input
		type="text"
		class="picker-input"
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
		<div class="picker-dropdown" role="listbox" id={listboxId} aria-label="Available datasources">
			{#if filteredOptions().length === 0}
				<div class="picker-empty">No datasources found</div>
			{:else}
				{#each filteredOptions() as ds (ds.id)}
					<button
						class="picker-option"
						class:selected={isSelected(ds.id)}
						class:highlighted={ds.id === highlightId}
						onmousedown={(e) => {
							e.preventDefault();
							toggle(ds.id, ds.name);
						}}
						role="option"
						aria-selected={isSelected(ds.id)}
						type="button"
					>
						<span class="option-name">{ds.name}</span>
						{#if ds.id === highlightId}
							<span class="option-badge current">current</span>
						{:else if ds.source_type === 'file'}
							<FileTypeBadge
								path={(ds.config?.file_path as string) ?? ''}
								size="sm"
								showIcon={false}
							/>
						{:else}
							<FileTypeBadge
								sourceType={ds.source_type as 'database' | 'api' | 'iceberg' | 'duckdb'}
								size="sm"
								showIcon={false}
							/>
						{/if}
					</button>
				{/each}
			{/if}
		</div>
	{/if}

	{#if mode === 'multi' && showChips && selectedDatasources().length > 0}
		<div class="picker-chips">
			{#each selectedDatasources() as ds (ds.id)}
				<span class="chip" class:highlighted={ds.id === highlightId}>
					{ds.name}
					<button
						class="chip-remove"
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

	{#if mode === 'multi' && showBulkActions && filteredOptions().length > 0}
		<div class="picker-actions">
			<button class="btn-secondary btn-sm" onclick={selectAll} type="button">Select All</button>
			<button class="btn-secondary btn-sm" onclick={deselectAll} type="button">Deselect All</button>
		</div>
	{/if}
</div>

<style>
	.datasource-picker {
		position: relative;
		width: 100%;
	}

	.picker-input {
		width: 100%;
		padding: var(--space-2) var(--space-3);
		font-size: var(--text-sm);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		background-color: var(--panel-bg);
		color: var(--fg-primary);
		font-family: var(--font-mono);
	}

	.picker-input:focus {
		outline: none;
		border-color: var(--accent-primary);
	}

	.picker-dropdown {
		position: absolute;
		top: 100%;
		left: 0;
		right: 0;
		margin-top: var(--space-1);
		background-color: var(--panel-bg);
		border: 1px solid var(--panel-border);
		border-radius: var(--radius-sm);
		box-shadow: var(--shadow-dropdown);
		z-index: var(--z-dropdown);
		max-height: 200px;
		overflow-y: auto;
	}

	.picker-option {
		display: flex;
		align-items: center;
		justify-content: space-between;
		width: 100%;
		padding: var(--space-2) var(--space-3);
		background: none;
		border: none;
		cursor: pointer;
		text-align: left;
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		color: var(--fg-primary);
		border-bottom: 1px solid var(--panel-border);
	}

	.picker-option:last-child {
		border-bottom: none;
	}

	.picker-option:hover {
		background-color: var(--bg-hover);
	}

	.picker-option.selected {
		background-color: var(--accent-bg);
	}

	.picker-option.highlighted {
		border-left: 3px solid var(--accent-primary);
	}

	.option-name {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.option-badge {
		font-size: var(--text-xs);
		padding: var(--space-1) var(--space-2);
		background-color: var(--badge-bg);
		border: 1px solid var(--badge-border);
		border-radius: var(--radius-sm);
		color: var(--badge-fg);
		margin-left: var(--space-2);
	}

	.option-badge.current {
		background-color: var(--info-bg);
		border-color: var(--info-border);
		color: var(--info-fg);
	}

	.picker-chips {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin-top: var(--space-2);
	}

	.chip {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		padding: var(--space-1) var(--space-2);
		background-color: var(--badge-bg);
		border: 1px solid var(--badge-border);
		border-radius: var(--radius-sm);
		font-size: var(--text-xs);
		color: var(--badge-fg);
	}

	.chip.highlighted {
		background-color: var(--info-bg);
		border-color: var(--info-border);
		color: var(--info-fg);
	}

	.chip-remove {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		padding: 0;
		background: none;
		border: none;
		cursor: pointer;
		color: var(--fg-muted);
		border-radius: var(--radius-sm);
		width: 16px;
		height: 16px;
	}

	.chip-remove:hover {
		color: var(--fg-primary);
		background-color: var(--bg-hover);
	}

	.picker-actions {
		display: flex;
		gap: var(--space-2);
		margin-top: var(--space-2);
	}

	.picker-empty {
		padding: var(--space-4);
		text-align: center;
		color: var(--fg-muted);
		font-size: var(--text-sm);
	}
</style>
