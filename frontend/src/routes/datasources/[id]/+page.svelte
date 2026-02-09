<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';

	const id = page.params.id;
	if (id) {
		goto(resolve('/datasources'), { replaceState: true });
	}
</script>

<div class="p-8 text-center">
	<p>Redirecting...</p>
</div>
