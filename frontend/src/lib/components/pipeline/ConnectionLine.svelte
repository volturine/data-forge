<script lang="ts">
	import { drag } from '$lib/stores/drag.svelte';
	import { css, cx } from '$lib/styles/panda';

	interface Props {
		fromStepIndex: number;
		toStepIndex: number;
		totalSteps: number;
		highlighted?: boolean;
		arrow?: boolean;
	}

	let {
		fromStepIndex: _fromStepIndex,
		toStepIndex: _toStepIndex,
		totalSteps: _totalSteps,
		highlighted = false,
		arrow = true
	}: Props = $props();

	const width = 12;
	const height = 12;
	const cx_ = width / 2;

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
				color: isDragActive ? (highlighted ? 'fg.primary' : 'fg.faint') : 'fg.faint',
				_hover: { color: 'fg.primary' }
			})
		)
	);
</script>

<div class={lineClass}>
	<svg {width} {height} xmlns="http://www.w3.org/2000/svg">
		<line
			x1={cx_}
			y1={0}
			x2={cx_}
			y2={arrow ? height - 6 : height}
			stroke="currentColor"
			stroke-width="1"
			stroke-dasharray="2 2"
		/>
		{#if arrow}
			<polyline
				points="{cx_ - 3},{height - 5} {cx_},{height - 1} {cx_ + 3},{height - 5}"
				fill="none"
				stroke="currentColor"
				stroke-width="1"
				stroke-linecap="round"
				stroke-linejoin="round"
			/>
		{/if}
	</svg>
</div>
