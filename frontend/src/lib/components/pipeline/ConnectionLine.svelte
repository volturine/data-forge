<script lang="ts">
	import { drag } from '$lib/stores/drag.svelte';

	interface Props {
		fromStepIndex: number;
		toStepIndex: number;
		totalSteps: number;
		highlighted?: boolean;
	}

	let {
		fromStepIndex: _fromStepIndex,
		toStepIndex: _toStepIndex,
		totalSteps: _totalSteps,
		highlighted = false
	}: Props = $props();

	const width = 24;
	const height = 32;
	const dotRadius = 2;
	const dotSpacing = 8;
	const arrowWidth = 8;
	const arrowHeight = 8;

	// Calculate dot positions
	let dots = $derived(
		Array.from(
			{ length: Math.floor((height - arrowHeight - 6) / dotSpacing) },
			(_, i) => i * dotSpacing + 6
		)
	);

	let isDragActive = $derived(drag.active);
</script>

<div class="connection-line" class:drag-active={isDragActive} class:highlighted>
	<svg {width} {height} xmlns="http://www.w3.org/2000/svg">
		<!-- Dotted vertical line -->
		{#each dots as y (y)}
			<circle cx={width / 2} cy={y} r={dotRadius} fill="currentColor" class="dot" />
		{/each}

		<!-- Arrow triangle pointing down -->
		<polygon
			points="{width / 2},{height - 2} {width / 2 - arrowWidth / 2},{height -
				arrowHeight -
				2} {width / 2 + arrowWidth / 2},{height - arrowHeight - 2}"
			fill="currentColor"
			class="arrow"
		/>
	</svg>
</div>

<style>
	.connection-line {
		width: 100%;
		display: flex;
		justify-content: center;
		align-items: center;
		color: var(--fg-muted);
		transition: color var(--transition);
	}

	.connection-line:hover {
		color: var(--fg-primary);
	}

	/* During drag: all connections visible but greyed out */
	.connection-line.drag-active {
		color: var(--fg-faint);
	}

	/* When highlighted (hovered insert zone): turn bright white */
	.connection-line.drag-active.highlighted {
		color: var(--fg-primary);
	}

	.connection-line svg {
		overflow: visible;
	}

	.dot {
		opacity: 0.8;
	}

	.arrow {
		opacity: 1;
	}
</style>
