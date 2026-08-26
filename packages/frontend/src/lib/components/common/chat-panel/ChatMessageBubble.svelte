<script lang="ts">
	import { CircleAlert, Copy, ClipboardCheck, Play, Eye } from '@lucide/svelte';
	import { onDestroy } from 'svelte';
	import { css } from '$lib/styles/panda';
	import { chatStore } from '$lib/stores/chat.svelte';
	import type { ChatMessage } from '$lib/stores/chat.svelte';
	import { renderMarkdown, timeAgo } from '$lib/utils/markdown';

	interface Props {
		msg: ChatMessage;
		grouped: boolean;
	}

	let { msg, grouped }: Props = $props();

	let copiedId = $state<string | null>(null);
	let copiedTimer: ReturnType<typeof setTimeout> | null = null;

	async function copyToClipboard(text: string, id: string) {
		await navigator.clipboard.writeText(text).catch(() => {});
		copiedId = id;
		if (copiedTimer) clearTimeout(copiedTimer);
		copiedTimer = setTimeout(() => {
			copiedTimer = null;
			if (copiedId === id) copiedId = null;
		}, 2000);
	}

	onDestroy(() => {
		if (copiedTimer) clearTimeout(copiedTimer);
	});
</script>

{#if msg.role === 'tool'}
	<!-- Tool error inline -->
	<div
		class={css({
			display: 'flex',
			alignItems: 'flex-start',
			gap: '1.5',
			paddingX: '2',
			paddingY: '1',
			borderRadius: 'sm',
			backgroundColor: 'bg.errorSubtle',
			borderLeftWidth: '2',
			borderColor: 'border.error',
			fontSize: '11px',
			color: 'fg.error'
		})}
	>
		<CircleAlert size={10} class={css({ flexShrink: '0', marginTop: '1px' })} />
		<pre
			class={css({
				margin: '0',
				whiteSpace: 'pre-wrap',
				wordBreak: 'break-word',
				fontFamily: 'mono',
				lineHeight: '1.4'
			})}>{msg.content}</pre>
	</div>
{:else}
	<!-- User / Assistant message -->
	<div
		class={[
			'chat-msg-enter',
			css({
				display: 'flex',
				flexDirection: msg.role === 'user' ? 'row-reverse' : 'row',
				gap: '1.5',
				marginTop: grouped ? '-0.5' : '0'
			})
		]}
	>
		{#if msg.role === 'assistant'}
			{#if !grouped}
				<div
					class={css({
						width: '22px',
						height: '22px',
						borderRadius: 'full',
						backgroundColor: chatStore.mode === 'execute' ? 'accent.primary' : 'bg.tertiary',
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'center',
						flexShrink: '0',
						marginTop: '1'
					})}
				>
					{#if chatStore.mode === 'execute'}
						<Play size={10} class={css({ color: 'white' })} />
					{:else}
						<Eye size={10} class={css({ color: 'fg.muted' })} />
					{/if}
				</div>
			{:else}
				<div class={css({ width: '22px', flexShrink: '0' })}></div>
			{/if}
		{/if}
		<div
			class={css({
				maxWidth: msg.role === 'assistant' ? 'calc(100% - 30px)' : '85%',
				display: 'flex',
				flexDirection: 'column',
				gap: '0.5',
				alignItems: msg.role === 'user' ? 'flex-end' : 'flex-start'
			})}
		>
			<div
				class={[
					css({
						padding: '2',
						borderRadius: 'md',
						fontSize: 'sm',
						backgroundColor: msg.role === 'user' ? 'bg.accent' : 'bg.tertiary',
						color: msg.role === 'user' ? 'fg.primary' : 'fg.primary',
						wordBreak: 'break-word',
						position: 'relative',
						lineHeight: '1.5',
						_hover: { '& .chat-copy-btn': { opacity: '1' } }
					}),
					msg.role === 'assistant' ? 'chat-markdown' : ''
				]}
			>
				{#if msg.role === 'assistant'}
					<!-- eslint-disable-next-line svelte/no-at-html-tags -- markdown from our own AI, not user-supplied HTML -->
					{@html renderMarkdown(msg.content)}
				{:else}
					<span class={css({ whiteSpace: 'pre-wrap' })}>{msg.content}</span>
				{/if}
				<button
					class={[
						'chat-copy-btn',
						css({
							position: 'absolute',
							top: '1',
							right: '1',
							padding: '1',
							border: 'none',
							backgroundColor: 'transparent',
							color: 'fg.muted',
							cursor: 'pointer',
							opacity: '0',
							_hover: { color: 'fg.primary' }
						})
					]}
					onclick={() => copyToClipboard(msg.content, msg.id)}
					title="Copy message"
					type="button"
				>
					{#if copiedId === msg.id}
						<ClipboardCheck size={11} />
					{:else}
						<Copy size={11} />
					{/if}
				</button>
			</div>
			<span
				class={[
					'chat-ts',
					css({
						fontSize: '10px',
						color: 'fg.muted',
						paddingX: '1'
					})
				]}
			>
				{timeAgo(msg.ts)}
			</span>
		</div>
	</div>
{/if}
