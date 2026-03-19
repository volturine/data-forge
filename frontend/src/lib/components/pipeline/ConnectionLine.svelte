<script lang="ts">
	import { drag } from '$lib/stores/drag.svelte';
	import { css, cx } from '$lib/styles/panda';

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
	const dots = $derived(
		Array.from(
			{ length: Math.floor((height - arrowHeight - 6) / dotSpacing) },
			(_, i) => i * dotSpacing + 6
		)
	);

	const isDragActive = $derived(drag.active);
	const lineClass = $derived(
		cx(
			'connection-line',
			css({
				display: 'flex',
				width: 'full',
				flexShrink: '0',
				alignItems: 'center',
				justifyContent: 'center',
				position: 'relative',
				zIndex: '1',
				height: 'pipelineConnection',
				color: isDragActive ? (highlighted ? 'fg.primary' : 'fg.faint') : 'fg.muted',
				_hover: { color: 'fg.primary' }
			})
		)
	);
</script>

<div class={lineClass}>
	<svg class={css({ overflow: 'visible' })} {width} {height} xmlns="http://www.w3.org/2000/svg">
		<!-- Dotted vertical line -->
		{#each dots as y (y)}
			<circle
				cx={width / 2}
				cy={y}
				r={dotRadius}
				fill="currentColor"
				class={css({ opacity: '0.8' })}
			/>
		{/each}

		<!-- Arrow triangle pointing down -->
		<polygon
			points="{width / 2},{height - 2} {width / 2 - arrowWidth / 2},{height -
				arrowHeight -
				2} {width / 2 + arrowWidth / 2},{height - arrowHeight - 2}"
			fill="currentColor"
		/>
	</svg>
</div>
