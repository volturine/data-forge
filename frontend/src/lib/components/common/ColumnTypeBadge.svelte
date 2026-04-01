<script lang="ts">
	import { getColumnTypeConfig } from '$lib/utils/column-types';
	import { css, cx, badge } from '$lib/styles/panda';

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
	const iconSize = $derived(size === 'xs' ? 11 : size === 'md' ? 14 : 12);
	const labelVisible = $derived(showLabel && variant !== 'compact');

	const sizes: Record<string, Record<string, string>> = {
		xs: { paddingX: '1.5', paddingY: '0.5', fontSize: 'xs', gap: 'px' },
		sm: { paddingX: '2', paddingY: '0.5', fontSize: 'xs', gap: '1' },
		md: { paddingX: '2.5', paddingY: '1', fontSize: 'sm', gap: '1' }
	};

	const variants: Record<string, Record<string, string>> = {
		default: {},
		subtle: { backgroundColor: 'transparent' },
		compact: { paddingX: '1', paddingY: '0.5', gap: '0' }
	};
</script>

<span
	class={cx(
		badge({ tone: 'type' }),
		css({
			fontWeight: 'semibold',
			whiteSpace: 'nowrap',
			lineHeight: '1',
			userSelect: 'none',
			transition: 'opacity 160ms',
			_hover: { opacity: '0.9' },
			...sizes[size],
			...variants[variant]
		})
	)}
	title={config.description}
>
	{#if showIcon}
		{@const IconComponent = config.icon}
		<IconComponent size={iconSize} strokeWidth={2.5} />
	{/if}
	{#if labelVisible}
		<span>{config.label}</span>
	{/if}
</span>
