<script lang="ts">
	import { formatDateDisplay, formatDateTimeDisplay, toEpochDisplay } from '#lib/utils/datetime.js';
	import { formatRelativeTime } from '#lib/utils/relative-time.js';
	import { subscribeVisibleClock } from '#lib/utils/visible-clock.js';
	import { css } from '#lib/styles/panda.js';

	interface Props {
		timestamp: string | number;
		live?: boolean;
		refreshMs?: number;
	}

	let { timestamp, live = true, refreshMs = 60_000 }: Props = $props();

	let now = $state(Date.now());

	// Subscribe to a shared browser timer; derived state cannot own timer cleanup.
	$effect(() => {
		if (!live) return;
		return subscribeVisibleClock(refreshMs, (tick) => {
			now = tick;
		});
	});

	const epoch = $derived(toEpochDisplay(timestamp));
	const relative = $derived(Number.isFinite(epoch) ? formatRelativeTime(epoch, now) : null);
	const label = $derived(relative ?? formatDateDisplay(timestamp));
	const iso = $derived(Number.isFinite(epoch) ? new Date(epoch).toISOString() : undefined);
</script>

<time
	class={css({
		whiteSpace: 'nowrap',
		fontVariantNumeric: 'tabular-nums'
	})}
	datetime={iso}
	title={formatDateTimeDisplay(timestamp)}>{label}</time
>
