<script lang="ts">
	import { getColumnTypesByCategory, CATEGORY_REGISTRY } from '$lib/utils/columnTypes';
	import type { ColumnTypeCategory } from '$lib/utils/columnTypes';
	import ColumnTypeBadge from './ColumnTypeBadge.svelte';

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

	// Calculate select width based on size
	const selectWidth = $derived(size === 'sm' ? '140px' : size === 'lg' ? '200px' : '160px');

	function handleChange(e: Event) {
		const target = e.currentTarget as HTMLSelectElement;
		value = target.value;
		onchange(target.value);
	}
</script>

<div
	class="inline-flex flex-wrap items-center gap-2 max-[480px]:flex-col max-[480px]:items-stretch"
>
	<select
		{id}
		{value}
		onchange={handleChange}
		{disabled}
		class="cursor-pointer rounded-sm border transition-all disabled:cursor-not-allowed disabled:opacity-60 hover:not-disabled:border-[var(--border-primary)] hover:not-disabled:bg-[var(--bg-primary)] focus:outline-2 focus:outline-offset-2 focus:outline-[var(--accent-primary)] focus:border-[var(--accent-primary)] max-[480px]:w-full {size ===
		'sm'
			? 'px-2 py-1 text-xs'
			: size === 'lg'
				? 'px-3 py-2 text-[0.9375rem]'
				: 'px-2.5 py-1.5 text-sm'}"
		style="min-width: {selectWidth}; background-color: var(--bg-secondary); border-color: var(--border-secondary); color: var(--fg-primary); font-family: var(--font-mono, monospace);"
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
		<div class="inline-flex items-center max-[480px]:justify-start">
			<ColumnTypeBadge columnType={value} size={size === 'lg' ? 'md' : 'sm'} />
		</div>
	{/if}
</div>
