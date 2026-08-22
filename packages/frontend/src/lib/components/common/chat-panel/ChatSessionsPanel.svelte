<script lang="ts">
	import { RefreshCw, Trash2 } from '@lucide/svelte';
	import { css } from '$lib/styles/panda';
	import { chatStore } from '$lib/stores/chat.svelte';
	import { timeAgo } from '$lib/utils/markdown';

	interface Props {
		maximized: boolean;
	}

	let { maximized }: Props = $props();
</script>

<div
	class={css({
		padding: '3',
		borderBottomWidth: '1',
		display: 'flex',
		flexDirection: 'column',
		gap: '2',
		minHeight: '0',
		overflowY: 'auto',
		...(maximized ? { flexShrink: '1', maxHeight: '55vh' } : { flex: '1' })
	})}
>
	<div
		class={css({
			display: 'flex',
			alignItems: 'center',
			gap: '1',
			fontSize: 'xs',
			color: 'fg.muted'
		})}
	>
		<span class={css({ flex: '1' })}>Sessions</span>
		<button
			class={css({
				background: 'none',
				border: 'none',
				cursor: 'pointer',
				padding: '0',
				color: 'fg.muted',
				display: 'flex',
				alignItems: 'center'
			})}
			onclick={() => void chatStore.loadSessions()}
			title="Refresh sessions"
			type="button"
		>
			<RefreshCw size={10} />
		</button>
	</div>
	<div
		class={css({
			display: 'flex',
			flexDirection: 'column',
			gap: '0',
			fontSize: 'xs'
		})}
	>
		{#each chatStore.sessions as session (session.id)}
			<div
				class={[
					'group',
					css({
						display: 'flex',
						alignItems: 'center',
						gap: '1',
						borderRadius: 'sm',
						overflow: 'hidden',
						_hover: { backgroundColor: 'bg.hover' }
					})
				]}
			>
				<button
					class={css({
						display: 'flex',
						flexDirection: 'column',
						gap: '0',
						flex: '1',
						textAlign: 'left',
						padding: '1.5',
						paddingX: '2',
						border: 'none',
						background: 'none',
						color: 'fg.secondary',
						cursor: 'pointer',
						minWidth: '0',
						overflow: 'hidden'
					})}
					onclick={() => void chatStore.resumeSession(session.id)}
					type="button"
					disabled={chatStore.loading}
				>
					<span
						class={css({
							fontSize: 'xs',
							overflow: 'hidden',
							textOverflow: 'ellipsis',
							whiteSpace: 'nowrap',
							color: session.preview ? 'fg.primary' : 'fg.muted'
						})}
					>
						{session.preview || 'Empty session'}
					</span>
					<span class={css({ fontSize: '10px', color: 'fg.muted', fontFamily: 'mono' })}>
						{session.model} · {timeAgo(session.created_at)}
					</span>
				</button>
				<button
					class={css({
						padding: '1',
						border: 'none',
						background: 'none',
						color: 'fg.muted',
						cursor: 'pointer',
						flexShrink: '0',
						borderRadius: 'sm',
						opacity: '0',
						_groupHover: { opacity: '1' },
						_hover: { color: 'fg.error', backgroundColor: 'bg.errorSubtle' }
					})}
					onclick={(e) => {
						e.stopPropagation();
						void chatStore.deleteSession(session.id);
					}}
					title="Delete session"
					type="button"
				>
					<Trash2 size={11} />
				</button>
			</div>
		{/each}
		{#if chatStore.sessions.length === 0}
			<span class={css({ color: 'fg.muted' })}>No sessions</span>
		{/if}
	</div>
</div>
