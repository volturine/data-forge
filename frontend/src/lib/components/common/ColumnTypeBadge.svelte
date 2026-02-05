<script lang="ts">
	import { getColumnTypeConfig } from '$lib/utils/columnTypes';

	interface Props {
		/** Column type name (handles aliases and normalization automatically) */
		columnType: string;
		/** Size variant */
		size?: 'xs' | 'sm' | 'md';
		/** Show icon next to label */
		showIcon?: boolean;
		/** Style variant */
		variant?: 'default' | 'subtle';
	}

	let { columnType, size = 'sm', showIcon = true, variant = 'default' }: Props = $props();

	// Get configuration for this column type
	const config = $derived(getColumnTypeConfig(columnType));

	// Calculate inline styles based on variant
	const containerStyle = $derived.by(() => {
		const { color, borderColor, backgroundColor } = config.colors;

		if (variant === 'subtle') {
			return `
				color: ${color};
				border: 1px solid ${borderColor};
				background-color: transparent;
			`;
		}

		// default variant
		return `
			color: ${color};
			border: 1px solid ${borderColor};
			background-color: ${backgroundColor};
		`;
	});

	// Size-based padding and font size
	const sizeStyles = $derived.by(() => {
		switch (size) {
			case 'xs':
				return 'padding: 2px 6px; font-size: 0.6875rem; gap: 3px;';
			case 'md':
				return 'padding: 4px 10px; font-size: 0.875rem; gap: 5px;';
			case 'sm':
			default:
				return 'padding: 3px 8px; font-size: 0.75rem; gap: 4px;';
		}
	});

	// Icon size based on badge size
	const iconSize = $derived(size === 'xs' ? 11 : size === 'md' ? 14 : 12);
</script>

<span class="column-type-badge" style="{containerStyle} {sizeStyles}" title={config.description}>
	{#if showIcon}
		{@const IconComponent = config.icon}
		<IconComponent size={iconSize} strokeWidth={2.5} />
	{/if}
	<span class="label">{config.label}</span>
</span>

<style>
	.column-type-badge {
		display: inline-flex;
		align-items: center;
		border-radius: var(--radius-sm, 4px);
		font-weight: 600;
		font-family: var(--font-mono, monospace);
		white-space: nowrap;
		transition: all 0.15s ease;
		line-height: 1;
		user-select: none;
	}

	.label {
		font-weight: 600;
		letter-spacing: 0.01em;
	}

	/* Optional: subtle hover effect */
	.column-type-badge:hover {
		opacity: 0.9;
	}
</style>
