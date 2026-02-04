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

<div class="column-type-select" style="--select-width: {selectWidth}">
	<select {id} {value} onchange={handleChange} {disabled} class="select-{size}">
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
		<div class="badge-container">
			<ColumnTypeBadge columnType={value} size={size === 'lg' ? 'md' : 'sm'} />
		</div>
	{/if}
</div>

<style>
	.column-type-select {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2, 0.5rem);
		flex-wrap: wrap;
	}

	select {
		min-width: var(--select-width, 160px);
		padding: var(--space-2, 0.5rem) var(--space-3, 0.75rem);
		background-color: var(--bg-secondary, #f8f9fa);
		border: 1px solid var(--border-secondary, #d1d5db);
		border-radius: var(--radius-sm, 4px);
		color: var(--fg-primary, #1f2937);
		font-size: var(--text-sm, 0.875rem);
		font-family: var(--font-mono, monospace);
		cursor: pointer;
		transition: all 0.15s ease;
	}

	select:hover:not(:disabled) {
		border-color: var(--border-primary, #9ca3af);
		background-color: var(--bg-primary, #ffffff);
	}

	select:focus {
		outline: 2px solid var(--accent-primary, #3b82f6);
		outline-offset: 2px;
		border-color: var(--accent-primary, #3b82f6);
	}

	select:disabled {
		opacity: 0.6;
		cursor: not-allowed;
		background-color: var(--bg-muted, #e5e7eb);
	}

	.select-sm {
		padding: 4px 8px;
		font-size: 0.75rem;
	}

	.select-md {
		padding: 6px 10px;
		font-size: 0.875rem;
	}

	.select-lg {
		padding: 8px 12px;
		font-size: 0.9375rem;
	}

	.badge-container {
		display: inline-flex;
		align-items: center;
	}

	optgroup {
		font-weight: 600;
		color: var(--fg-muted, #6b7280);
		font-size: 0.75rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		padding-top: 0.25rem;
	}

	option {
		font-family: var(--font-mono, monospace);
		padding: 0.25rem 0.5rem;
	}

	/* Responsive: stack vertically on very small screens */
	@media (max-width: 480px) {
		.column-type-select {
			flex-direction: column;
			align-items: stretch;
		}

		select {
			width: 100%;
		}

		.badge-container {
			justify-content: flex-start;
		}
	}
</style>
