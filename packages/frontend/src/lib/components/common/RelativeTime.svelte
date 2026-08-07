<script lang="ts">
	import { formatDateDisplay, formatDateTimeDisplay, toEpochDisplay } from '$lib/utils/datetime';
	import { formatRelativeTime } from '$lib/utils/relative-time';
	import { css } from '$lib/styles/panda';

	interface Props {
		timestamp: string | number;
		live?: boolean;
		refreshMs?: number;
	}

	let { timestamp, live = true, refreshMs = 60_000 }: Props = $props();

	let now = $state(Date.now());

	$effect(() => {
		if (!live) return;
		const interval = setInterval(() => {
			now = Date.now();
		}, refreshMs);
		return () => clearInterval(interval);
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
