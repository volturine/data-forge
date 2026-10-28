<script lang="ts">
	import { CheckCircle, XCircle } from '@lucide/svelte';
	import { css } from '#lib/styles/panda.js';

	let { kind, message }: { kind: 'success' | 'error'; message: string } = $props();
</script>

<div
	class={css({
		display: 'flex',
		alignItems: 'center',
		gap: '2',
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
	{#if kind === 'success'}
		<CheckCircle size={14} />
	{:else}
		<XCircle size={14} />
	{/if}
	{message}
</div>
