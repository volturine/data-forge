<script lang="ts">
	interface Props {
		onSearch: (query: string) => void;
		onSort: (sortOption: SortOption) => void;
	}

	export type SortOption = 'newest' | 'oldest' | 'name-asc' | 'name-desc';

	let { onSearch, onSort }: Props = $props();

	let searchQuery = $state('');
	let sortOption = $state<SortOption>('newest');

	function handleSearchInput(e: Event) {
		const target = e.target as HTMLInputElement;
		searchQuery = target.value;
		onSearch(searchQuery);
	}

	function handleSortChange(e: Event) {
		const target = e.target as HTMLSelectElement;
		sortOption = target.value as SortOption;
		onSort(sortOption);
	}

	function clearSearch() {
		searchQuery = '';
		onSearch('');
	}
</script>

<div class="filters">
	<div class="search-box">
		<svg
			class="search-icon"
			xmlns="http://www.w3.org/2000/svg"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
		>
			<circle cx="11" cy="11" r="8" stroke-width="2" />
			<path d="M21 21l-4.35-4.35" stroke-width="2" />
		</svg>
		<input
			type="text"
			placeholder="Search analyses..."
			value={searchQuery}
			oninput={handleSearchInput}
			class="search-input"
		/>
		{#if searchQuery}
			<button class="clear-btn" onclick={clearSearch} aria-label="Clear search">
				<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor">
					<path d="M18 6L6 18M6 6l12 12" stroke-width="2" />
				</svg>
			</button>
		{/if}
	</div>

	<div class="sort-box">
		<label for="sort-select" class="sort-label">Sort by:</label>
		<select id="sort-select" value={sortOption} onchange={handleSortChange} class="sort-select">
			<option value="newest">Newest First</option>
			<option value="oldest">Oldest First</option>
			<option value="name-asc">Name A-Z</option>
			<option value="name-desc">Name Z-A</option>
		</select>
	</div>
</div>

<style>
	.filters {
		display: flex;
		gap: 16px;
		align-items: center;
		margin-bottom: 24px;
		flex-wrap: wrap;
	}

	.search-box {
		position: relative;
		flex: 1;
		min-width: 240px;
	}

	.search-icon {
		position: absolute;
		left: 12px;
		top: 50%;
		transform: translateY(-50%);
		width: 20px;
		height: 20px;
		color: #9e9e9e;
		pointer-events: none;
	}

	.search-input {
		width: 100%;
		padding: 12px 40px 12px 44px;
		border: 1px solid #e0e0e0;
		border-radius: 8px;
		font-size: 15px;
		color: #212121;
		background: white;
		transition: all 0.2s;
	}

	.search-input:focus {
		outline: none;
		border-color: #1976d2;
		box-shadow: 0 0 0 3px rgba(25, 118, 210, 0.1);
	}

	.search-input::placeholder {
		color: #9e9e9e;
	}

	.clear-btn {
		position: absolute;
		right: 8px;
		top: 50%;
		transform: translateY(-50%);
		background: none;
		border: none;
		padding: 6px;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		border-radius: 4px;
		color: #9e9e9e;
		transition: all 0.2s;
	}

	.clear-btn:hover {
		background: #f5f5f5;
		color: #424242;
	}

	.clear-btn svg {
		width: 18px;
		height: 18px;
		stroke-width: 2;
	}

	.sort-box {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.sort-label {
		font-size: 14px;
		color: #757575;
		font-weight: 500;
		white-space: nowrap;
	}

	.sort-select {
		padding: 10px 36px 10px 14px;
		border: 1px solid #e0e0e0;
		border-radius: 8px;
		font-size: 15px;
		color: #212121;
		background: white url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23757575'%3E%3Cpath d='M6 9l6 6 6-6' stroke-width='2'/%3E%3C/svg%3E")
			no-repeat right 8px center;
		background-size: 20px;
		cursor: pointer;
		appearance: none;
		transition: all 0.2s;
		min-width: 160px;
	}

	.sort-select:focus {
		outline: none;
		border-color: #1976d2;
		box-shadow: 0 0 0 3px rgba(25, 118, 210, 0.1);
	}

	.sort-select:hover {
		border-color: #bdbdbd;
	}

	@media (max-width: 640px) {
		.filters {
			flex-direction: column;
			align-items: stretch;
		}

		.search-box {
			min-width: 0;
		}

		.sort-box {
			flex-direction: column;
			align-items: flex-start;
			gap: 6px;
		}

		.sort-select {
			width: 100%;
		}
	}
</style>
