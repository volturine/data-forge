<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';

	// Navigation side-effect: $derived cannot perform imperative redirects.
	$effect(() => {
		const url = `/monitoring${page.url.search}`;
		goto(resolve(url as '/'), { replaceState: true });
	});
</script>

<div class="mx-auto max-w-300 px-6 py-7">
	<div class="border border-tertiary bg-bg-secondary p-4 text-sm text-fg-tertiary">
		Redirecting to Monitoring schedules...
	</div>
</div>
