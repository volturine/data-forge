<script lang="ts">
	import { untrack } from 'svelte';
	import { useSvelteFlow } from '@xyflow/svelte';

	export type LineageFlowApi = Pick<
		ReturnType<typeof useSvelteFlow>,
		'zoomIn' | 'zoomOut' | 'fitView' | 'getZoom'
	>;

	type Props = {
		onready: (api: LineageFlowApi) => void;
	};

	let { onready }: Props = $props();

	const flow = useSvelteFlow();

	// The api object is exposed exactly once at initialization; onready is not
	// read reactively on purpose.
	// Pass the flow helpers through unchanged so callers can await their transitions.
	untrack(() => onready(flow));
</script>
