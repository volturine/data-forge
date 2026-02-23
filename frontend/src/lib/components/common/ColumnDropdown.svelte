<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import ColumnTypeBadge from '$lib/components/common/ColumnTypeBadge.svelte';
	import SearchableDropdown from '$lib/components/ui/SearchableDropdown.svelte';

	interface ColumnOption {
		id: string;
		label: string;
		dtype: string;
	}

	interface Props {
		schema: Schema;
		value: string;
		onChange: (value: string) => void;
		placeholder?: string;
		filter?: (column: { name: string; dtype: string }) => boolean;
	}

	let {
		schema,
		value = $bindable(),
		onChange,
		placeholder = 'Select column...',
		filter
	}: Props = $props();

	const columns = $derived(filter ? schema.columns.filter(filter) : schema.columns);
	const options = $derived(
		columns.map((column) => ({
			id: column.name,
			label: column.name,
			dtype: column.dtype
		}))
	);

</script>

<SearchableDropdown
	options={options}
	value={value}
	onChange={(next) => onChange(next as string)}
	placeholder={placeholder}
	searchPlaceholder="Search columns..."
	renderOption={renderOption}
/>

{#snippet renderOption(payload: { option: { id: string; label: string }; selected: boolean; onSelect: () => void })}
	{@const item = payload.option as ColumnOption}
	{@const isSelected = payload.selected}
	{@const onPick = payload.onSelect}
	<button
		type="button"
		class="column-option"
		class:selected={isSelected}
		onclick={onPick}
		role="option"
		aria-selected={isSelected}
	>
		<ColumnTypeBadge columnType={item.dtype} size="xs" variant="compact" />
		<span>{item.label}</span>
	</button>
{/snippet}
