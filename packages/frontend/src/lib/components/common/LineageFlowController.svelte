<script lang="ts">
	import { untrack } from 'svelte';
	import { useSvelteFlow } from '@xyflow/svelte';

	export interface LineageFlowApi {
		zoomIn: () => void;
		zoomOut: () => void;
		fitView: () => void;
		getZoom: () => number;
	}

	type Props = {
		onready: (api: LineageFlowApi) => void;
	};

	let { onready }: Props = $props();

	const flow = useSvelteFlow();

	// The api object is exposed exactly once at initialization; onready is not
	// read reactively on purpose.
	untrack(() =>
		onready({
			zoomIn: () => void flow.zoomIn(),
			zoomOut: () => void flow.zoomOut(),
			fitView: () => void flow.fitView(),
			getZoom: () => flow.getZoom()
		})
	);
</script>
