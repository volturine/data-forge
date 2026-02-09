<script lang="ts">
	import { getColumnTypeConfig, type ColumnTypeCategory } from '$lib/utils/columnTypes';

	interface Props {
		columnType: string;
		size?: 'xs' | 'sm' | 'md';
		showIcon?: boolean;
		variant?: 'default' | 'subtle';
	}

	let { columnType, size = 'sm', showIcon = true, variant = 'default' }: Props = $props();

	const config = $derived(getColumnTypeConfig(columnType));

	const categoryClass = $derived(getCategoryClass(config.category));
	const sizeClass = $derived(`size-${size}`);
	const variantClass = $derived(`variant-${variant}`);
	const iconSize = $derived(size === 'xs' ? 11 : size === 'md' ? 14 : 12);

	function getCategoryClass(category: ColumnTypeCategory): string {
		return `category-${category}`;
	}
</script>

<span class="type-badge {categoryClass} {sizeClass} {variantClass}" title={config.description}>
	{#if showIcon}
		{@const IconComponent = config.icon}
		<IconComponent size={iconSize} strokeWidth={2.5} />
	{/if}
	<span>{config.label}</span>
</span>
