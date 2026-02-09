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
	let lineClass = $derived(
		`connection-line flex w-full shrink-0 items-center justify-center transition-colors h-pipeline-connection${
			isDragActive ? ' drag-active' : ''
		}${highlighted ? ' highlighted' : ''}`
	);
</script>

<div class={lineClass}>
	<svg class="overflow-visible" {width} {height} xmlns="http://www.w3.org/2000/svg">
		<!-- Dotted vertical line -->
		{#each dots as y (y)}
			<circle cx={width / 2} cy={y} r={dotRadius} fill="currentColor" class="opacity-80" />
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
