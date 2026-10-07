<script lang="ts">
	import { css } from '$lib/styles/panda';

	let { kind, message }: { kind: 'success' | 'error'; message: string } = $props();
</script>

<div
	class={css({
		borderWidth: '1',
		borderColor: kind === 'success' ? 'border.success' : 'border.error',
		backgroundColor: kind === 'success' ? 'bg.success' : 'bg.error',
		color: kind === 'success' ? 'fg.success' : 'fg.error',
		paddingX: '3',
		paddingY: '2',
		fontSize: 'sm'
	})}
	role={kind === 'error' ? 'alert' : 'status'}
>
	{message}
</div>
