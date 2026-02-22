<script lang="ts">
	import { getColumnTypeConfig, type ColumnTypeCategory } from '$lib/utils/columnTypes';

	interface Props {
		columnType: string;
		size?: 'xs' | 'sm' | 'md';
		showIcon?: boolean;
		showLabel?: boolean;
		variant?: 'default' | 'subtle' | 'compact';
	}

	let {
		columnType,
		size = 'sm',
		showIcon = true,
		showLabel = true,
		variant = 'default'
	}: Props = $props();

	const config = $derived(getColumnTypeConfig(columnType));

	const categoryClass = $derived(getCategoryClass(config.category));
	const sizeClass = $derived(`size-${size}`);
	const variantClass = $derived(`variant-${variant}`);
	const iconSize = $derived(size === 'xs' ? 11 : size === 'md' ? 14 : 12);
	const labelVisible = $derived(showLabel && variant !== 'compact');

	function getCategoryClass(category: ColumnTypeCategory): string {
		return `category-${category}`;
	}
</script>

<span class="type-badge {categoryClass} {sizeClass} {variantClass}" title={config.description}>
	{#if showIcon}
		{@const IconComponent = config.icon}
		<IconComponent size={iconSize} strokeWidth={2.5} />
	{/if}
	{#if labelVisible}
		<span>{config.label}</span>
	{/if}
</span>
