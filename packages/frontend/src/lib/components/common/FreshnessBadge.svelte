<script lang="ts">
	import { onMount } from 'svelte';
	import { chip } from '$lib/styles/panda';
	import { formatDateTimeDisplay, toEpochDisplay } from '$lib/utils/datetime';
	import { freshnessStatus, type FreshnessStatus } from '$lib/utils/freshness';

	interface Props {
		lastDataUpdate?: string | null;
		thresholdMinutes?: number | null;
		live?: boolean;
	}

	let { lastDataUpdate, thresholdMinutes = null, live = true }: Props = $props();

	let now = $state(Date.now());

	onMount(() => {
		if (!live) return;
		const interval = setInterval(() => {
			now = Date.now();
		}, 60_000);
		return () => clearInterval(interval);
	});

	const epoch = $derived(lastDataUpdate ? toEpochDisplay(lastDataUpdate) : NaN);
	const status = $derived(
		freshnessStatus(Number.isFinite(epoch) ? epoch : null, thresholdMinutes, now)
	);

	const labels: Record<FreshnessStatus, string> = {
		fresh: 'Fresh',
		stale: 'Stale',
		outdated: 'Outdated',
		unknown: 'Unknown'
	};

	const tones: Record<FreshnessStatus, 'success' | 'warning' | 'error' | 'neutral'> = {
		fresh: 'success',
		stale: 'warning',
		outdated: 'error',
		unknown: 'neutral'
	};
</script>

<span
	class={chip({ tone: tones[status] })}
	data-freshness={status}
	role="status"
	title={lastDataUpdate ? formatDateTimeDisplay(lastDataUpdate) : 'No data has been built yet'}
>
	{labels[status]}
</span>
