<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import ColumnTypeBadge from '$lib/components/common/ColumnTypeBadge.svelte';
	import SearchableDropdown from '$lib/components/ui/SearchableDropdown.svelte';
	import { css } from '$lib/styles/panda';

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
		clearable?: boolean;
		triggerClass?: string;
		menuClass?: string;
	}

	let {
		schema,
		value = $bindable(),
		onChange,
		placeholder = 'Select column...',
		filter,
		clearable = false,
		triggerClass = '',
		menuClass = ''
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
	{options}
	{value}
	onChange={(next) => onChange(next as string)}
	{placeholder}
	{clearable}
	searchPlaceholder="Search columns..."
	{triggerClass}
	{menuClass}
	{renderOption}
/>

{#snippet renderOption(payload: {
	option: { id: string; label: string };
	selected: boolean;
	onSelect: () => void;
})}
	{@const item = payload.option as ColumnOption}
	{@const isSelected = payload.selected}
	{@const onPick = payload.onSelect}
	<button
		type="button"
		data-column-option={item.label}
		class={css(
			{
				minWidth: '0',
				width: '100%',
				paddingX: '3',
				paddingY: '2',
				borderWidth: '1',
				borderColor: 'transparent',
				background: 'transparent',
				textAlign: 'left',
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'flex-start',
				gap: '2',
				cursor: 'pointer',
				fontSize: 'sm',
				'& span': { minWidth: '0', overflowWrap: 'anywhere' },
				_hover: { backgroundColor: 'bg.hover' }
			},
			isSelected && { backgroundColor: 'bg.hover' }
		)}
		onclick={onPick}
		role="option"
		aria-selected={isSelected}
	>
		<ColumnTypeBadge columnType={item.dtype} size="xs" variant="compact" />
		<span>{item.label}</span>
	</button>
{/snippet}
