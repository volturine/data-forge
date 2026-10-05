<script lang="ts">
	import type { PipelineStep } from '$lib/types/analysis';
	import { css } from '$lib/styles/panda';
	import { getStepTypeConfig } from './utils';

	interface Props {
		steps: PipelineStep[];
		canvasEl?: HTMLElement | null;
	}

	interface Marker {
		key: string;
		selector: string;
		label: string;
		kind: 'source' | 'step' | 'output';
		applied: boolean;
		top: number;
		height: number;
	}

	let { steps, canvasEl = null }: Props = $props();

	let markers = $state<Marker[]>([]);
	let viewTop = $state(0);
	let viewHeight = $state(1);
	let hoveredKey = $state<string | null>(null);
	let railEl = $state<HTMLElement | null>(null);
	let frame = 0;

	const targets = $derived([
		{
			key: 'source',
			selector: '#pipeline-datasource-node',
			label: 'Source',
			kind: 'source' as const,
			applied: true
		},
		...steps.map((step, index) => ({
			key: step.id,
			selector: `[id="step-node-${step.id}"]`,
			label: `${index + 1}. ${getStepTypeConfig(step.type).label}`,
			kind: 'step' as const,
			applied: step.is_applied !== false
		})),
		{
			key: 'output',
			selector: '#pipeline-output-node',
			label: 'Output',
			kind: 'output' as const,
			applied: true
		}
	]);

	const hovered = $derived(markers.find((marker) => marker.key === hoveredKey) ?? null);

	function measure() {
		frame = 0;
		if (!canvasEl) return;
		const total = canvasEl.scrollHeight;
		if (total <= 0) return;
		const originTop = canvasEl.getBoundingClientRect().top - canvasEl.scrollTop;
		const next: Marker[] = [];
		for (const target of targets) {
			const node = canvasEl.querySelector<HTMLElement>(target.selector);
			if (!node) continue;
			const rect = node.getBoundingClientRect();
			next.push({
				...target,
				top: (rect.top - originTop) / total,
				height: rect.height / total
			});
		}
		markers = next;
		viewTop = canvasEl.scrollTop / total;
		viewHeight = Math.min(1, canvasEl.clientHeight / total);
	}

	function scheduleMeasure() {
		if (frame) return;
		frame = requestAnimationFrame(measure);
	}

	$effect(() => {
		const el = canvasEl;
		void targets;
		if (!el) return;
		measure();
		const resizeObserver = new ResizeObserver(scheduleMeasure);
		resizeObserver.observe(el);
		for (const child of el.children) resizeObserver.observe(child);
		el.addEventListener('scroll', scheduleMeasure, { passive: true });
		return () => {
			resizeObserver.disconnect();
			el.removeEventListener('scroll', scheduleMeasure);
			if (frame) cancelAnimationFrame(frame);
			frame = 0;
		};
	});

	function scrollToMarker(marker: Marker) {
		canvasEl
			?.querySelector<HTMLElement>(marker.selector)
			?.scrollIntoView({ behavior: 'smooth', block: 'center' });
	}

	function scrollToPointer(event: PointerEvent) {
		if (!canvasEl || !railEl) return;
		const rect = railEl.getBoundingClientRect();
		const fraction = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height));
		canvasEl.scrollTop = fraction * canvasEl.scrollHeight - canvasEl.clientHeight / 2;
	}

	function handleRailPointerDown(event: PointerEvent) {
		if (event.button !== 0) return;
		railEl?.setPointerCapture(event.pointerId);
		scrollToPointer(event);
	}

	function handleRailPointerMove(event: PointerEvent) {
		if (!railEl?.hasPointerCapture(event.pointerId)) return;
		scrollToPointer(event);
	}

	const markerTone = {
		endpoint: css({ backgroundColor: 'accent.primary' }),
		visible: css({ backgroundColor: 'fg.muted' }),
		offscreen: css({ backgroundColor: 'fg.faint' }),
		disabled: css({ backgroundColor: 'border.secondary' })
	};

	function toneFor(marker: Marker): string {
		if (marker.kind !== 'step') return markerTone.endpoint;
		if (!marker.applied) return markerTone.disabled;
		const inView = marker.top + marker.height > viewTop && marker.top < viewTop + viewHeight;
		return inView ? markerTone.visible : markerTone.offscreen;
	}
</script>

<nav
	aria-label="Pipeline overview"
	data-testid="pipeline-minimap"
	class={css({
		position: 'absolute',
		top: '3',
		bottom: '12',
		right: '1',
		width: '4',
		zIndex: '10',
		opacity: '0.55',
		transitionProperty: 'opacity',
		transitionDuration: '160ms',
		_hover: { opacity: '1' },
		_focusWithin: { opacity: '1' }
	})}
>
	<div
		bind:this={railEl}
		data-testid="minimap-rail"
		role="presentation"
		onpointerdown={handleRailPointerDown}
		onpointermove={handleRailPointerMove}
		class={css({
			position: 'absolute',
			inset: '0',
			cursor: 'pointer',
			touchAction: 'none'
		})}
	>
		<div
			class={css({
				position: 'absolute',
				top: '0',
				bottom: '0',
				left: '50%',
				width: '1px',
				backgroundColor: 'border.primary'
			})}
		></div>
		<div
			data-testid="minimap-viewport"
			class={css({
				position: 'absolute',
				left: '0',
				right: '0',
				borderRadius: 'xs',
				backgroundColor: 'bg.tertiary',
				borderWidth: '1',
				borderColor: 'border.secondary',
				pointerEvents: 'none'
			})}
			style:top={`${viewTop * 100}%`}
			style:height={`${viewHeight * 100}%`}
		></div>
		{#each markers as marker (marker.key)}
			<button
				type="button"
				data-testid={`minimap-marker-${marker.key}`}
				aria-label={`Go to ${marker.label}`}
				onpointerdown={(event) => event.stopPropagation()}
				onclick={() => scrollToMarker(marker)}
				onpointerenter={() => (hoveredKey = marker.key)}
				onpointerleave={() => (hoveredKey = null)}
				onfocus={() => (hoveredKey = marker.key)}
				onblur={() => (hoveredKey = null)}
				class={[
					toneFor(marker),
					css({
						position: 'absolute',
						left: '1.5',
						right: '1.5',
						minHeight: '1',
						padding: '0',
						borderWidth: '0',
						borderRadius: 'full',
						cursor: 'pointer',
						transitionProperty: 'background-color',
						transitionDuration: '160ms',
						_focusVisible: { outlineWidth: '2', outlineColor: 'border.accent' }
					})
				]}
				style:top={`${marker.top * 100}%`}
				style:height={`${marker.height * 100}%`}
			></button>
		{/each}
	</div>
	{#if hovered}
		<span
			data-testid="minimap-label"
			class={css({
				position: 'absolute',
				right: '5',
				transform: 'translateY(-50%)',
				whiteSpace: 'nowrap',
				pointerEvents: 'none',
				paddingX: '1.5',
				paddingY: '0.5',
				fontSize: '2xs',
				color: 'fg.secondary',
				backgroundColor: 'bg.primary',
				borderWidth: '1',
				borderColor: 'border.secondary',
				borderRadius: 'xs'
			})}
			style:top={`${(hovered.top + hovered.height / 2) * 100}%`}
		>
			{hovered.label}{hovered.applied ? '' : ' (disabled)'}
		</span>
	{/if}
</nav>
