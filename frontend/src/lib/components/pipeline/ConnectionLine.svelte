<script lang="ts">
	interface Props {
		fromStepIndex: number;
		toStepIndex: number;
		totalSteps: number;
	}

	let { fromStepIndex, toStepIndex, totalSteps: _totalSteps }: Props = $props();

	const height = 32;
	const strokeWidth = 2;
	const arrowSize = 6;
	const dashArray = '4,4';
</script>

<div class="connection-line">
	<svg width="100%" {height} xmlns="http://www.w3.org/2000/svg">
		<defs>
			<marker
				id="arrowhead-{fromStepIndex}-{toStepIndex}"
				markerWidth={arrowSize}
				markerHeight={arrowSize}
				refX={arrowSize - 1}
				refY={arrowSize / 2}
				orient="auto"
			>
				<polygon points="0 0, {arrowSize} {arrowSize / 2}, 0 {arrowSize}" fill="#d1d5db" />
			</marker>
		</defs>

		<line
			x1="50%"
			y1="0"
			x2="50%"
			y2={height}
			stroke="#d1d5db"
			stroke-width={strokeWidth}
			stroke-dasharray={dashArray}
			marker-end="url(#arrowhead-{fromStepIndex}-{toStepIndex})"
		/>
	</svg>
</div>

<style>
	.connection-line {
		width: 100%;
		max-width: 400px;
		position: relative;
		animation: fadeIn 0.3s ease-in;
	}

	@keyframes fadeIn {
		from {
			opacity: 0;
		}
		to {
			opacity: 1;
		}
	}
</style>
