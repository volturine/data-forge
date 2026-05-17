<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { css } from '$lib/styles/panda';

	const id = page.params.id;
	if (id) {
		goto(resolve('/datasources'), { replaceState: true });
	}
</script>

<div class={css({ padding: '8', textAlign: 'center' })}>
	<p>Redirecting...</p>
</div>
