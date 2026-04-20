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
	{options}
	{value}
	onChange={(next) => onChange(next as string[])}
	{placeholder}
	searchPlaceholder="Search columns..."
	mode="multi"
	{showSelectAll}
	showSelectedList={true}
	{renderOption}
/>

{#snippet renderOption(payload: {
	option: { id: string; label: string };
	selected: boolean;
	onSelect: () => void;
})}
	{@const item = payload.option as ColumnOption}
	<label
		class={css({
			display: 'flex',
			cursor: 'pointer',
			alignItems: 'center',
			fontSize: 'sm',
			fontWeight: 'normal',
			color: 'fg.secondary',
			textTransform: 'none',
			letterSpacing: 'normal',
			marginBottom: '0',
			gap: '2',
			paddingX: '3',
			paddingY: '2',
			_hover: { backgroundColor: 'bg.hover' }
		})}
	>
		<input
			type="checkbox"
			id="msc-col-{item.id}"
			checked={payload.selected}
			onchange={payload.onSelect}
			onclick={(event) => event.stopPropagation()}
			class={css({ margin: '0', cursor: 'pointer' })}
		/>
		<span
			class={css({
				display: 'flex',
				flex: '1',
				alignItems: 'center',
				justifyContent: 'flex-start',
				gap: '2'
			})}
		>
			<ColumnTypeBadge columnType={item.dtype} size="xs" variant="compact" />
			<span class={css({ textAlign: 'left', fontSize: 'sm' })}>{item.label}</span>
		</span>
	</label>
{/snippet}
