<script lang="ts">
	import ColumnTypeBadge from '$lib/components/common/ColumnTypeBadge.svelte';
	import SearchableDropdown from '$lib/components/ui/SearchableDropdown.svelte';
	import { getAllColumnTypes } from '$lib/utils/columnTypes';

	interface ColumnTypeOption {
		id: string;
		label: string;
		type: string;
		description?: string;
	}

	interface Props {
		value: string;
		onChange: (value: string) => void;
		placeholder?: string;
		disabled?: boolean;
	}

	let {
		value = $bindable(),
		onChange,
		placeholder = 'Select type...',
		disabled = false
	}: Props = $props();

	const allColumnTypes = getAllColumnTypes();
	const options = $derived(
		allColumnTypes.map((entry) => ({
			id: entry.type,
			label: entry.label,
			type: entry.type,
			description: entry.description
		}))
	);
</script>

<SearchableDropdown
	options={options}
	value={value}
	onChange={(next) => onChange(next as string)}
	placeholder={placeholder}
	searchPlaceholder="Search types..."
	disabled={disabled}
	renderOption={renderOption}
 />

{#snippet renderOption(payload: { option: { id: string; label: string }; selected: boolean; onSelect: () => void })}
	{@const item = payload.option as ColumnTypeOption}
	<button
		type="button"
		class="column-option type-option"
		class:selected={payload.selected}
		onclick={payload.onSelect}
		role="option"
		aria-selected={payload.selected}
		title={item.description}
	>
		<ColumnTypeBadge columnType={item.type} size="sm" />
	</button>
{/snippet}
