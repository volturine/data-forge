<script lang="ts">
	import { css } from '$lib/styles/panda';
	import 'styled-system/styles.css';

	let { children } = $props();
</script>

<div
	class={css({
		display: 'flex',
		alignItems: 'center',
		justifyContent: 'center',
		minHeight: '100vh',
		backgroundColor: 'bg.secondary'
	})}
>
	<div class={css({ width: '100%', maxWidth: '400px', paddingX: '4' })}>
		{@render children()}
	</div>
</div>
