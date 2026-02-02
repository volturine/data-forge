<script lang="ts">
	import { Search, X } from 'lucide-svelte';

	export type SortOption = 'newest' | 'oldest' | 'name-asc' | 'name-desc';

	interface Props {
		searchQuery: string;
		sortOption: SortOption;
		onSearch: (query: string) => void;
		onSort: (option: SortOption) => void;
	}

	let { searchQuery, sortOption, onSearch, onSort }: Props = $props();
</script>

<div class="filters">
	<div class="search-box">
		<Search class="search-icon" size={16} />
		<input
			type="text"
			placeholder="Search analyses..."
			value={searchQuery}
			oninput={(e) => onSearch((e.target as HTMLInputElement).value)}
			class="search-input"
		/>
		{#if searchQuery}
			<button class="clear-btn" onclick={() => onSearch('')} aria-label="Clear search">
				<X size={14} />
			</button>
		{/if}
	</div>

	<div class="sort-box">
		<label for="sort-select" class="sort-label">Sort:</label>
		<select
			id="sort-select"
			value={sortOption}
			onchange={(e) => onSort((e.target as HTMLSelectElement).value as SortOption)}
			class="sort-select"
		>
			<option value="newest">Newest</option>
			<option value="oldest">Oldest</option>
			<option value="name-asc">A-Z</option>
			<option value="name-desc">Z-A</option>
		</select>
	</div>
</div>

<style>
	.filters {
		display: flex;
		gap: var(--space-4);
		align-items: center;
		margin-bottom: var(--space-7);
		flex-wrap: wrap;
	}
	.search-box {
		position: relative;
		flex: 1;
		min-width: 220px;
		max-width: 420px;
	}
	.search-box :global(.search-icon) {
		position: absolute;
		left: var(--space-3);
		top: 50%;
		transform: translateY(-50%);
		color: var(--fg-muted);
		pointer-events: none;
	}
	.search-input {
		width: 100%;
		padding: var(--space-3) var(--space-10) var(--space-3) var(--space-10);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		color: var(--fg-primary);
		background-color: var(--bg-primary);
		transition:
			border-color var(--transition),
			box-shadow var(--transition);
		box-shadow: var(--card-shadow);
	}
	.search-input:focus {
		outline: none;
		border-color: var(--border-focus);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--border-focus) 20%, transparent);
	}
	.search-input::placeholder {
		color: var(--fg-muted);
	}
	.clear-btn {
		position: absolute;
		right: var(--space-2);
		top: 50%;
		transform: translateY(-50%);
		background: transparent;
		border: none;
		padding: var(--space-1);
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		border-radius: var(--radius-sm);
		color: var(--fg-muted);
		transition: all var(--transition);
	}
	.clear-btn:hover {
		background-color: var(--bg-hover);
		color: var(--fg-primary);
	}
	.sort-box {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}
	.sort-label {
		font-size: var(--text-xs);
		color: var(--fg-muted);
		font-weight: 500;
		white-space: nowrap;
	}
	.sort-select {
		padding: var(--space-2) var(--space-8) var(--space-2) var(--space-3);
		border: 1px solid var(--border-primary);
		border-radius: var(--radius-sm);
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		color: var(--fg-primary);
		background-color: var(--bg-primary);
		background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%23737373' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");
		background-repeat: no-repeat;
		background-position: right var(--space-2) center;
		cursor: pointer;
		appearance: none;
		transition: border-color var(--transition);
	}
	.sort-select:focus {
		outline: none;
		border-color: var(--border-focus);
	}
	.sort-select:hover {
		border-color: var(--border-tertiary);
	}
	@media (max-width: 640px) {
		.filters {
			flex-direction: column;
			align-items: stretch;
		}
		.search-box {
			max-width: none;
		}
		.sort-box {
			justify-content: space-between;
		}
		.sort-select {
			flex: 1;
		}
	}
</style>
