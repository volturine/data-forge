<script lang="ts">
	import { Search, X, Trash2 } from 'lucide-svelte';
	import { css, input, cx, label } from '$lib/styles/panda';

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

<div
	class={css({
		marginBottom: '7',
		display: 'flex',
		flexWrap: 'wrap',
		alignItems: 'center',
		gap: '4',
		smDown: { flexDirection: 'column', alignItems: 'stretch' }
	})}
>
	<div
		class={css({
			position: 'relative',
			minWidth: 'dropdown',
			maxWidth: 'panel',
			flex: '1',
			smDown: { maxWidth: 'none' }
		})}
	>
		<Search
			class={css({
				pointerEvents: 'none',
				position: 'absolute',
				left: '3',
				top: '50%',
				transform: 'translateY(-50%)',
				color: 'fg.muted'
			})}
			size={16}
		/>
		<input
			type="text"
			id="filters-search"
			aria-label="Search analyses"
			placeholder="Search analyses..."
			value={searchQuery}
			oninput={(e) => onSearch((e.target as HTMLInputElement).value)}
			class={input({ variant: 'searchWide' })}
		/>
		{#if searchQuery}
			<button
				class={css({
					display: 'flex',
					alignItems: 'center',
					position: 'absolute',
					right: '2',
					top: '50%',
					transform: 'translateY(-50%)',
					cursor: 'pointer',
					justifyContent: 'center',
					borderWidth: '0',
					backgroundColor: 'transparent',
					padding: '1',
					color: 'fg.muted'
				})}
				onclick={() => onSearch('')}
				aria-label="Clear search"
			>
				<X size={14} />
			</button>
		{/if}
	</div>

	<div
		class={css({
			display: 'flex',
			alignItems: 'center',
			gap: '2',
			smDown: { justifyContent: 'space-between' }
		})}
	>
		<label
			for="sort-select"
			class={cx(label(), css({ whiteSpace: 'nowrap', fontWeight: 'medium' }))}
		>
			Sort:
		</label>
		<select
			id="sort-select"
			value={sortOption}
			onchange={(e) => onSort((e.target as HTMLSelectElement).value as SortOption)}
			class={cx(
				input(),
				css({
					cursor: 'pointer',
					appearance: 'none',
					paddingRight: '8',
					smDown: { flex: '1' }
				})
			)}
		>
			<option value="newest">Newest</option>
			<option value="oldest">Oldest</option>
			<option value="name-asc">A-Z</option>
			<option value="name-desc">Z-A</option>
		</select>
	</div>

	{#if selectionCount > 0}
		<div class={css({ display: 'flex', alignItems: 'center', marginLeft: 'auto', gap: '2' })}>
			<button
				class={css({
					display: 'flex',
					alignItems: 'center',
					gap: '1',
					borderWidth: '1',
					borderColor: 'transparent',
					backgroundColor: 'transparent',
					paddingX: '3',
					paddingY: '2',
					fontSize: 'sm'
				})}
				onclick={onSelectAll}
			>
				Select All
			</button>
			<button
				class={css({
					display: 'flex',
					alignItems: 'center',
					gap: '1',
					borderWidth: '1',
					borderColor: 'transparent',
					backgroundColor: 'transparent',
					paddingX: '3',
					paddingY: '2',
					fontSize: 'sm'
				})}
				onclick={onClearSelection}
			>
				<X size={14} />
				Clear
			</button>
			<button
				class={css({
					display: 'flex',
					alignItems: 'center',
					gap: '1',
					backgroundColor: 'bg.error',
					color: 'fg.error',
					borderWidth: '1',
					borderColor: 'border.error',
					paddingX: '3',
					paddingY: '2'
				})}
				onclick={onBulkDelete}
			>
				<Trash2 size={14} />
				Delete
			</button>
		</div>
	{/if}
</div>
