<script lang="ts">
	import { ArrowDown, CircleAlert, RotateCcw, X, Eye, Play, History, Trash2 } from '@lucide/svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import { css } from '$lib/styles/panda';
	import { chatStore } from '$lib/stores/chat.svelte';
	import { timelineDateSeparator, timelineEntriesAreGrouped } from '$lib/chat/presentation';
	import { timeAgo } from '$lib/utils/markdown';
	import { nowEpochMs } from '$lib/utils/temporal';
	import ChatMessageBubble from './ChatMessageBubble.svelte';
	import ToolCallCard from './ToolCallCard.svelte';

	interface Props {
		onSendPrompt: (text: string) => void;
		onFocusInput: () => void;
	}

	let { onSendPrompt, onFocusInput }: Props = $props();

	let messagesEl: HTMLElement | undefined;
	let userScrolledUp = $state(false);

	function bindMessages(el: HTMLElement) {
		messagesEl = el;
	}

	function handleScroll() {
		if (!messagesEl) return;
		const { scrollTop, scrollHeight, clientHeight } = messagesEl;
		userScrolledUp = scrollHeight - scrollTop - clientHeight > 80;
	}

	function scrollToBottom() {
		if (messagesEl) {
			messagesEl.scrollTo({ top: messagesEl.scrollHeight, behavior: 'smooth' });
			userScrolledUp = false;
		}
	}

	export function resetScroll() {
		userScrolledUp = false;
	}

	// DOM scroll after timeline update — $derived cannot trigger rAF
	const timelineLength = $derived(chatStore.timeline.length);
	const isLoading = $derived(chatStore.loading);
	$effect(() => {
		void timelineLength;
		void isLoading;
		if (!userScrolledUp && messagesEl) {
			requestAnimationFrame(() => {
				requestAnimationFrame(() => {
					messagesEl?.scrollTo({ top: messagesEl.scrollHeight, behavior: 'smooth' });
				});
			});
		}
	});

	// Timers created by injected copy buttons — cleared when the effect tears down
	const pendingTimers = new SvelteSet<ReturnType<typeof setTimeout>>();
	$effect(() => () => {
		for (const t of pendingTimers) clearTimeout(t);
	});

	// DOM mutation: $derived can't inject buttons into rendered HTML.
	$effect(() => {
		void timelineLength;
		if (!messagesEl) return;
		const buttons: HTMLButtonElement[] = [];
		requestAnimationFrame(() => {
			const blocks = messagesEl?.querySelectorAll('.chat-markdown pre');
			if (!blocks) return;
			for (const block of blocks) {
				if (block.querySelector('.code-copy-btn')) continue;
				const pre = block as HTMLElement;
				pre.style.position = 'relative';
				const btn = document.createElement('button');
				btn.className = 'code-copy-btn';
				btn.title = 'Copy code';
				btn.innerHTML =
					'<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>';
				btn.addEventListener('click', () => {
					const code = pre.querySelector('code')?.textContent ?? pre.textContent ?? '';
					void navigator.clipboard.writeText(code).then(() => {
						btn.innerHTML =
							'<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
						const t = setTimeout(() => {
							pendingTimers.delete(t);
							btn.innerHTML =
								'<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>';
						}, 2000);
						pendingTimers.add(t);
					});
				});
				pre.appendChild(btn);
				buttons.push(btn);
			}
		});
		return () => {
			for (const btn of buttons) {
				btn.remove();
			}
		};
	});

	function isGrouped(idx: number): boolean {
		return timelineEntriesAreGrouped(chatStore.timeline, idx);
	}

	function dateSeparator(idx: number): string | null {
		return timelineDateSeparator(chatStore.timeline, idx);
	}

	const EXAMPLE_PROMPTS = [
		'List all data sources',
		'Show recent analyses',
		'What tools are available?'
	];

	/** Reactive elapsed timer — ticks every second while a tool is running. */
	let elapsedTick = $state(nowEpochMs());
	$effect(() => {
		const hasRunning = chatStore.toolCalls.some((tc) => tc.status === 'running' && tc.startedAt);
		if (!hasRunning) return;
		const iv = setInterval(() => {
			elapsedTick = nowEpochMs();
		}, 1000);
		return () => clearInterval(iv);
	});

	function collapseAllTools() {
		for (const tc of chatStore.toolCalls) {
			tc.expanded = false;
		}
	}

	function expandAllTools() {
		for (const tc of chatStore.toolCalls) {
			tc.expanded = true;
		}
	}

	const hasToolCalls = $derived(chatStore.toolCalls.length > 0);

	const showQuickReplies = $derived.by(() => {
		if (chatStore.loading) return false;
		if (chatStore.mode !== 'plan') return false;
		for (let i = chatStore.timeline.length - 1; i >= 0; i--) {
			const entry = chatStore.timeline[i];
			if (entry.kind === 'message') {
				return entry.item.role === 'assistant';
			}
		}
		return false;
	});
</script>

<!-- Messages area -->
<div
	class={css({
		flex: '1',
		overflowY: 'auto',
		padding: '3',
		display: 'flex',
		flexDirection: 'column',
		gap: '1.5',
		minHeight: '0',
		position: 'relative'
	})}
	use:bindMessages
	onscroll={handleScroll}
>
	<!-- Empty state -->
	{#if chatStore.timeline.length === 0 && !chatStore.loading}
		<div
			class={css({
				flex: '1',
				display: 'flex',
				flexDirection: 'column',
				alignItems: 'center',
				justifyContent: 'center',
				gap: '3',
				paddingY: '6',
				color: 'fg.muted'
			})}
		>
			<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
				{#if chatStore.mode === 'plan'}
					<Eye size={24} class={css({ opacity: '0.4' })} />
				{:else}
					<Play size={24} class={css({ opacity: '0.4' })} />
				{/if}
			</div>
			<div class={css({ textAlign: 'center' })}>
				<p class={css({ fontSize: 'sm', margin: '0', marginBottom: '1' })}>
					{chatStore.mode === 'plan'
						? 'Plan mode — read-only, proposes before acting'
						: 'Execute mode — full access, acts directly'}
				</p>
				<p class={css({ fontSize: 'xs', margin: '0', color: 'fg.muted' })}>
					{chatStore.sessionId
						? 'Send a message to get started.'
						: 'Start a session and ask anything.'}
				</p>
			</div>
			{#if chatStore.configured}
				<div
					class={css({
						display: 'flex',
						flexDirection: 'column',
						gap: '1.5',
						width: '100%',
						maxWidth: '280px'
					})}
				>
					{#each EXAMPLE_PROMPTS as prompt (prompt)}
						<button
							class={css({
								display: 'block',
								width: '100%',
								textAlign: 'left',
								padding: '2',
								paddingX: '3',
								fontSize: 'xs',
								borderWidth: '1',
								borderRadius: 'md',
								backgroundColor: 'transparent',
								color: 'fg.secondary',
								cursor: 'pointer',
								_hover: { backgroundColor: 'bg.tertiary' }
							})}
							onclick={() => onSendPrompt(prompt)}
							type="button"
							disabled={chatStore.loading}
						>
							{prompt}
						</button>
					{/each}
				</div>
			{/if}
			{#if chatStore.sessions.length > 0}
				<div
					class={css({
						display: 'flex',
						flexDirection: 'column',
						gap: '1',
						width: '100%',
						maxWidth: '280px'
					})}
				>
					<div
						class={css({
							display: 'flex',
							alignItems: 'center',
							gap: '1',
							fontSize: '10px',
							color: 'fg.muted',
							fontWeight: 'medium',
							textTransform: 'uppercase',
							letterSpacing: 'wide'
						})}
					>
						<History size={10} />
						Recent sessions
					</div>
					{#each chatStore.sessions.slice(0, 5) as session (session.id)}
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
								<span
									class={css({
										fontSize: '10px',
										color: 'fg.muted',
										fontFamily: 'mono'
									})}
								>
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
				</div>
			{/if}
		</div>
	{/if}

	<!-- Timeline controls -->
	{#if hasToolCalls}
		<div
			class={css({
				display: 'flex',
				justifyContent: 'flex-end',
				paddingX: '2',
				paddingY: '0.5'
			})}
		>
			<button
				class={css({
					border: 'none',
					background: 'none',
					padding: '0',
					cursor: 'pointer',
					color: 'fg.muted',
					fontSize: '10px',
					fontFamily: 'mono',
					_hover: { color: 'fg.primary' }
				})}
				onclick={() => {
					const anyExpanded = chatStore.toolCalls.some((tc) => tc.expanded);
					if (anyExpanded) collapseAllTools();
					else expandAllTools();
				}}
				type="button"
			>
				{chatStore.toolCalls.some((tc) => tc.expanded) ? 'Collapse all tools' : 'Expand all tools'}
			</button>
		</div>
	{/if}

	<!-- Timeline -->
	{#each chatStore.timeline as entry, idx (entry.kind === 'message' ? entry.item.id : entry.item.tool_id + idx)}
		{@const dateLabel = dateSeparator(idx)}
		{@const grouped = isGrouped(idx)}
		{#if dateLabel}
			<div
				class={css({
					display: 'flex',
					alignItems: 'center',
					gap: '3',
					paddingY: '1'
				})}
			>
				<div class={css({ flex: '1', height: '1px', backgroundColor: 'border.subtle' })}></div>
				<span class={css({ fontSize: '10px', color: 'fg.muted', whiteSpace: 'nowrap' })}
					>{dateLabel}</span
				>
				<div class={css({ flex: '1', height: '1px', backgroundColor: 'border.subtle' })}></div>
			</div>
		{/if}
		{#if entry.kind === 'message'}
			<ChatMessageBubble msg={entry.item} {grouped} />
		{:else}
			<ToolCallCard tc={entry.item} tick={elapsedTick} />
		{/if}
	{/each}

	<!-- Typing indicator -->
	{#if chatStore.loading && chatStore.timeline.length > 0}
		<div class={css({ display: 'flex', gap: '2', marginLeft: '30px' })}>
			<div
				class={css({
					padding: '1.5',
					paddingX: '3',
					borderRadius: 'md',
					backgroundColor: 'bg.tertiary',
					display: 'flex',
					alignItems: 'center',
					gap: '1'
				})}
			>
				<span class="chat-dot chat-dot-1"></span>
				<span class="chat-dot chat-dot-2"></span>
				<span class="chat-dot chat-dot-3"></span>
			</div>
		</div>
	{/if}

	<!-- Quick replies (plan mode only) -->
	{#if showQuickReplies}
		<div
			class={css({
				display: 'flex',
				gap: '2',
				paddingTop: '1',
				marginLeft: '30px',
				flexWrap: 'wrap'
			})}
		>
			<button
				class={css({
					paddingX: '3',
					paddingY: '1',
					borderRadius: 'full',
					borderWidth: '1',
					borderColor: 'border.accent',
					backgroundColor: 'transparent',
					color: 'accent.primary',
					fontSize: '11px',
					fontWeight: 'medium',
					cursor: 'pointer',
					_hover: { backgroundColor: 'bg.accent', color: 'fg.primary' }
				})}
				onclick={() => onSendPrompt('Go ahead, execute the plan.')}
				type="button"
			>
				Execute plan
			</button>
			<button
				class={css({
					paddingX: '3',
					paddingY: '1',
					borderRadius: 'full',
					borderWidth: '1',
					backgroundColor: 'transparent',
					color: 'fg.muted',
					fontSize: '11px',
					cursor: 'pointer',
					_hover: { backgroundColor: 'bg.tertiary' }
				})}
				onclick={onFocusInput}
				type="button"
			>
				Modify
			</button>
		</div>
	{/if}
</div>

<!-- Scroll to bottom -->
{#if userScrolledUp}
	<div class={css({ position: 'relative' })}>
		<button
			class={css({
				position: 'absolute',
				bottom: '2',
				left: '50%',
				transform: 'translateX(-50%)',
				display: 'flex',
				alignItems: 'center',
				gap: '1',
				paddingX: '3',
				paddingY: '1',
				borderRadius: 'full',
				borderWidth: '1',
				backgroundColor: 'bg.panel',
				color: 'fg.muted',
				fontSize: '11px',
				cursor: 'pointer',
				boxShadow: 'md',
				zIndex: '1',
				_hover: { backgroundColor: 'bg.tertiary' }
			})}
			onclick={scrollToBottom}
			type="button"
		>
			<ArrowDown size={10} />
			{chatStore.loading ? 'New messages' : 'Jump to latest'}
		</button>
	</div>
{/if}

<!-- Error banner -->
{#if chatStore.error}
	<div
		class={css({
			display: 'flex',
			alignItems: 'center',
			gap: '2',
			paddingX: '3',
			paddingY: '1.5',
			borderTopWidth: '1',
			borderColor: 'border.error',
			backgroundColor: 'bg.errorSubtle',
			flexShrink: '0'
		})}
	>
		<CircleAlert size={11} class={css({ color: 'fg.error', flexShrink: '0' })} />
		<span
			class={css({
				flex: '1',
				color: 'fg.error',
				fontSize: '11px',
				overflow: 'hidden',
				textOverflow: 'ellipsis'
			})}
		>
			{chatStore.error}
		</span>
		{#if chatStore.lastFailedContent}
			<button
				class={css({
					display: 'flex',
					alignItems: 'center',
					gap: '1',
					padding: '1',
					paddingX: '2',
					border: 'none',
					borderRadius: 'sm',
					backgroundColor: 'transparent',
					color: 'fg.error',
					fontSize: '11px',
					fontWeight: 'medium',
					cursor: 'pointer',
					flexShrink: '0',
					_hover: { backgroundColor: 'bg.tertiary' }
				})}
				onclick={() => void chatStore.retry()}
				type="button"
			>
				<RotateCcw size={10} />
				Retry
			</button>
		{/if}
		<button
			class={css({
				padding: '1',
				border: 'none',
				backgroundColor: 'transparent',
				color: 'fg.error',
				cursor: 'pointer',
				flexShrink: '0',
				_hover: { opacity: '0.7' }
			})}
			onclick={() => chatStore.dismissError()}
			type="button"
			title="Dismiss error"
		>
			<X size={11} />
		</button>
	</div>
{/if}
