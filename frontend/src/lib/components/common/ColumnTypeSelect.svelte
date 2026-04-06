<script lang="ts">
	import { getColumnTypesByCategory, CATEGORY_REGISTRY } from '$lib/utils/column-types';
	import type { ColumnTypeCategory } from '$lib/utils/column-types';
	import ColumnTypeBadge from './ColumnTypeBadge.svelte';
	import { css, cx, input } from '$lib/styles/panda';

	interface Props {
		/** Selected column type value */
		value: string;
		/** Change handler */
		onchange: (value: string) => void;
		/** Filter to specific categories (optional) */
		categories?: ColumnTypeCategory[];
		/** Size variant */
		size?: 'sm' | 'md' | 'lg';
		/** Show badge next to select */
		showBadge?: boolean;
		/** Placeholder text for empty option */
		placeholder?: string;
		/** Disabled state */
		disabled?: boolean;
		/** Custom id for the select element */
		id?: string;
	}

	let {
		value = $bindable(),
		onchange,
		categories,
		size = 'md',
		showBadge = true,
		placeholder,
		disabled = false,
		id
	}: Props = $props();

	// Get all types grouped by category
	const allTypesByCategory = getColumnTypesByCategory();

	// Filter categories if specified
	const typesByCategory = $derived.by(() => {
		if (!categories || categories.length === 0) {
			return allTypesByCategory;
		}

		const filtered: Partial<typeof allTypesByCategory> = {};
		categories.forEach((cat) => {
			if (allTypesByCategory[cat]) {
				filtered[cat] = allTypesByCategory[cat];
			}
		});
		return filtered as typeof allTypesByCategory;
	});

	function handleChange(e: Event) {
		const target = e.currentTarget as HTMLSelectElement;
		value = target.value;
		onchange(target.value);
	}
</script>

<div
	class={css({
		display: 'inline-flex',
		flexWrap: 'wrap',
		alignItems: 'center',
		gap: '2',
		smDown: { alignItems: 'stretch' }
	})}
>
	<select
		{id}
		{value}
		onchange={handleChange}
		{disabled}
		class={cx(
			input(),
			css({
				cursor: 'pointer',
				backgroundColor: 'bg.secondary',
				smDown: { width: '100%' }
			}),
			size === 'sm'
				? css({ paddingX: '2', paddingY: '1', fontSize: 'xs', minWidth: 'inputSm' })
				: size === 'lg'
					? css({ paddingX: '3', paddingY: '2', fontSize: 'sm', minWidth: 'listSm' })
					: css({ paddingX: '2.5', paddingY: '1.5', fontSize: 'sm', minWidth: 'inputSm' })
		)}
	>
		{#if placeholder}
			<option value="">{placeholder}</option>
		{/if}

		{#each Object.entries(typesByCategory) as [category, types] (category)}
			{#if types.length > 0}
				<optgroup label={CATEGORY_REGISTRY[category as ColumnTypeCategory].label}>
					{#each types as typeConfig (typeConfig.type)}
						<option value={typeConfig.type}>{typeConfig.label}</option>
					{/each}
				</optgroup>
			{/if}
		{/each}
	</select>

	{#if showBadge && value}
		<div
			class={css({
				display: 'inline-flex',
				alignItems: 'center',
				smDown: { justifyContent: 'flex-start' }
			})}
		>
			<ColumnTypeBadge columnType={value} size={size === 'lg' ? 'md' : 'sm'} />
		</div>
	{/if}
</div>
