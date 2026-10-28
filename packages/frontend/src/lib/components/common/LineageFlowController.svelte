<script lang="ts">
	import { onDestroy, untrack } from 'svelte';
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
	let pendingFit: Promise<boolean> | null = null;
	let disposed = false;
	let resolveDisposed: (() => void) | undefined;
	const disposedPromise = new Promise<void>((resolve) => {
		resolveDisposed = resolve;
	});

	onDestroy(() => {
		disposed = true;
		pendingFit = null;
		resolveDisposed?.();
	});

	function rememberFit(promise: Promise<boolean>): Promise<boolean> {
		pendingFit = promise;
		void promise.then(
			() => {
				if (pendingFit === promise) pendingFit = null;
			},
			() => {
				if (pendingFit === promise) pendingFit = null;
			}
		);
		return promise;
	}

	async function zoomAfterPendingFit(zoom: () => Promise<boolean>): Promise<boolean> {
		while (pendingFit && !disposed) {
			// A failed fit is settled too; it must not disable manual viewport controls.
			await Promise.race([pendingFit.catch(() => false), disposedPromise]);
		}
		return disposed ? false : zoom();
	}

	function fitView(...args: Parameters<typeof flow.fitView>): ReturnType<typeof flow.fitView> {
		return rememberFit(flow.fitView(...args));
	}

	function zoomIn(...args: Parameters<typeof flow.zoomIn>): ReturnType<typeof flow.zoomIn> {
		if (disposed) return Promise.resolve(false);
		if (!pendingFit) return flow.zoomIn(...args);
		return zoomAfterPendingFit(() => flow.zoomIn(...args));
	}

	function zoomOut(...args: Parameters<typeof flow.zoomOut>): ReturnType<typeof flow.zoomOut> {
		if (disposed) return Promise.resolve(false);
		if (!pendingFit) return flow.zoomOut(...args);
		return zoomAfterPendingFit(() => flow.zoomOut(...args));
	}

	// fitView's prop queues the initial autofit without exposing its resolver. Calling
	// the helper here reuses that queued fit and gives zoom requests something to await.
	rememberFit(flow.fitView());

	const api: LineageFlowApi = {
		zoomIn,
		zoomOut,
		fitView,
		getZoom: flow.getZoom
	};

	// The api object is exposed exactly once at initialization; onready is not
	// read reactively on purpose.
	untrack(() => onready(api));
</script>
