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
		value: string[];
		onChange: (value: string[]) => void;
		placeholder?: string;
		filter?: (column: { name: string; dtype: string }) => boolean;
		showSelectAll?: boolean;
	}

	let {
		schema,
		value = $bindable([]),
		onChange,
		placeholder = 'Select columns...',
		filter,
		showSelectAll = true
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
	onChange={(next) => onChange(next as string[])}
	placeholder={placeholder}
	searchPlaceholder="Search columns..."
	mode="multi"
	showSelectAll={showSelectAll}
	showSelectedList={true}
	renderOption={renderOption}
 />

{#snippet renderOption(payload: { option: { id: string; label: string }; selected: boolean; onSelect: () => void })}
	{@const item = payload.option as ColumnOption}
	<label class="multi-select-option flex cursor-pointer items-center gap-2 px-3 py-2 text-fg-primary">
		<input
			type="checkbox"
			checked={payload.selected}
			onchange={payload.onSelect}
			onclick={(event) => event.stopPropagation()}
			class="m-0 cursor-pointer accent-primary"
		/>
		<span class="flex flex-1 items-center justify-start gap-2">
			<ColumnTypeBadge columnType={item.dtype} size="xs" variant="compact" />
			<span class="text-left text-sm text-fg-primary">{item.label}</span>
		</span>
	</label>
{/snippet}
