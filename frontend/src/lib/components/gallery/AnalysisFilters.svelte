<script lang="ts">
	import { Search, X, Trash2 } from 'lucide-svelte';

	export type SortOption = 'newest' | 'oldest' | 'name-asc' | 'name-desc';

	interface Props {
		searchQuery: string;
		sortOption: SortOption;
		onSearch: (query: string) => void;
		onSort: (option: SortOption) => void;
		selectionCount?: number;
		onSelectAll?: () => void;
		onClearSelection?: () => void;
		onBulkDelete?: () => void;
	}

	let {
		searchQuery,
		sortOption,
		onSearch,
		onSort,
		selectionCount = 0,
		onSelectAll,
		onClearSelection,
		onBulkDelete
	}: Props = $props();
</script>

<div class="mb-7 flex flex-wrap items-center gap-4 max-sm:flex-col max-sm:items-stretch">
	<div class="relative min-w-55 max-w-105 flex-1 max-sm:max-w-none">
		<Search
			class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-muted"
			size={16}
		/>
		<input
			type="text"
			placeholder="Search analyses..."
			value={searchQuery}
			oninput={(e) => onSearch((e.target as HTMLInputElement).value)}
			class="search-input input-styled w-full border py-3 pl-10 pr-10 font-mono text-sm"
		/>
		{#if searchQuery}
			<button
				class="clear-btn absolute right-2 top-1/2 flex -translate-y-1/2 cursor-pointer items-center justify-center border-none bg-transparent p-1 text-fg-muted"
				onclick={() => onSearch('')}
				aria-label="Clear search"
			>
				<X size={14} />
			</button>
		{/if}
	</div>

	<div class="flex items-center gap-2 max-sm:justify-between">
		<label for="sort-select" class="whitespace-nowrap text-xs font-medium text-fg-muted">
			Sort:
		</label>
		<select
			id="sort-select"
			value={sortOption}
			onchange={(e) => onSort((e.target as HTMLSelectElement).value as SortOption)}
			class="sort-select input-styled cursor-pointer appearance-none border bg-no-repeat py-2 pl-3 pr-8 font-mono text-sm max-sm:flex-1"
		>
			<option value="newest">Newest</option>
			<option value="oldest">Oldest</option>
			<option value="name-asc">A-Z</option>
			<option value="name-desc">Z-A</option>
		</select>
	</div>

	{#if selectionCount > 0}
		<div class="ml-auto flex items-center gap-2">
			<button
				class="btn-text flex items-center gap-1 border border-transparent bg-transparent px-3 py-2 text-sm"
				onclick={onSelectAll}
			>
				Select All
			</button>
			<button
				class="btn-text flex items-center gap-1 border border-transparent bg-transparent px-3 py-2 text-sm"
				onclick={onClearSelection}
			>
				<X size={14} />
				Clear
			</button>
			<button class="btn-danger flex items-center gap-1" onclick={onBulkDelete}>
				<Trash2 size={14} />
				Delete
			</button>
		</div>
	{/if}
</div>
