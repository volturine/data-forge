<script lang="ts">
	import ColumnTypeBadge from '$lib/components/common/ColumnTypeBadge.svelte';
	import SearchableDropdown from '$lib/components/ui/SearchableDropdown.svelte';
	import { css, cx } from '$lib/styles/panda';
	import { getAllColumnTypes } from '$lib/utils/column-types';

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
		allowed?: string[];
	}

	let {
		value = $bindable(),
		onChange,
		placeholder = 'Select type...',
		disabled = false,
		allowed
	}: Props = $props();

	const allColumnTypes = getAllColumnTypes();
	const allowedSet = $derived(allowed ? new Set(allowed) : null);
	const options = $derived(
		allColumnTypes
			.filter((entry) => !allowedSet || allowedSet.has(entry.type))
			.map((entry) => ({
				id: entry.type,
				label: entry.label,
				type: entry.type,
				description: entry.description
			}))
	);
</script>

<SearchableDropdown
	{options}
	{value}
	onChange={(next) => onChange(next as string)}
	{placeholder}
	searchPlaceholder="Search types..."
	{disabled}
	{renderOption}
/>

{#snippet renderOption(payload: {
	option: { id: string; label: string };
	selected: boolean;
	onSelect: () => void;
})}
	{@const item = payload.option as ColumnTypeOption}
	<button
		type="button"
		class={cx(
			css({
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
			}),
			css({ minWidth: 'auto', padding: '2', justifyContent: 'center' }),
			payload.selected && css({ backgroundColor: 'bg.hover' })
		)}
		onclick={payload.onSelect}
		role="option"
		aria-selected={payload.selected}
		title={item.description}
	>
		<ColumnTypeBadge columnType={item.type} size="sm" />
	</button>
{/snippet}
