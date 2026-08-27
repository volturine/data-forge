<script lang="ts">
	import {
		X,
		LoaderCircle,
		Eye,
		Play,
		Wrench,
		History,
		Settings2,
		Maximize2,
		Minimize2,
		Plus
	} from '@lucide/svelte';
	import { onMount } from 'svelte';
	import { css, iconButton } from '$lib/styles/panda';
	import { useQueryClient } from '@tanstack/svelte-query';
	import { chatStore } from '$lib/stores/chat.svelte';
	import { overlayStack } from '$lib/stores/overlay.svelte';
	import type { OverlayConfig } from '$lib/stores/overlay.svelte';
	import type { ChatUiPatchEvent } from '$lib/api/chat';
	import { stopGeneration as stopChatGeneration } from '$lib/api/chat';
	import { ChatPanelLayout } from '$lib/chat/panel-layout.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import ChatMessages from './chat-panel/ChatMessages.svelte';
	import ChatComposer from './chat-panel/ChatComposer.svelte';
	import ChatConfigPanel from './chat-panel/ChatConfigPanel.svelte';
	import ChatToolsPanel from './chat-panel/ChatToolsPanel.svelte';
	import ChatSessionsPanel from './chat-panel/ChatSessionsPanel.svelte';

	const queryClient = useQueryClient();

	let configOpen = $state(false);
	let toolsOpen = $state(false);
	let sessionsOpen = $state(false);
	let inputValue = $state('');
	let inputEl = $state<HTMLTextAreaElement | undefined>();
	let messagesRef = $state<{ resetScroll(): void } | undefined>();
	const layout = new ChatPanelLayout();
	const anyPanelOpen = $derived(configOpen || toolsOpen || sessionsOpen);
	if (typeof window !== 'undefined') layout.restore();

	function focusInput() {
		requestAnimationFrame(() => inputEl?.focus());
	}

	function focusPanel(node: HTMLElement) {
		requestAnimationFrame(() => {
			const textarea = node.querySelector('textarea');
			if (textarea instanceof HTMLTextAreaElement) textarea.focus();
		});
	}

	async function stopGeneration() {
		if (chatStore.sessionId) {
			await stopChatGeneration(chatStore.sessionId);
		}
		chatStore.loading = false;
		focusInput();
	}

	async function handleSend() {
		const text = inputValue.trim();
		if (!text) return;
		const sent = await chatStore.send(text);
		if (sent) {
			inputValue = '';
			messagesRef?.resetScroll();
			if (inputEl) {
				inputEl.style.height = 'auto';
				focusInput();
			}
		}
	}

	async function handleSendPrompt(text: string) {
		inputValue = '';
		const sent = await chatStore.send(text);
		if (!sent) {
			inputValue = text;
			return;
		}
		focusInput();
	}

	function togglePanel(panel: 'config' | 'tools' | 'sessions') {
		if (panel === 'config') {
			configOpen = !configOpen;
			toolsOpen = false;
			sessionsOpen = false;
			if (configOpen && chatStore.models.length === 0) {
				void chatStore.loadModels();
			}
		} else if (panel === 'tools') {
			toolsOpen = !toolsOpen;
			configOpen = false;
			sessionsOpen = false;
		} else if (panel === 'sessions') {
			sessionsOpen = !sessionsOpen;
			configOpen = false;
			toolsOpen = false;
			if (sessionsOpen) {
				void chatStore.loadSessions();
			}
		}
	}

	function onPatch(e: Event) {
		const detail = (e as CustomEvent<ChatUiPatchEvent>).detail;
		const resource = detail.resource;
		if (!resource) return;
		if (resource === 'analysis' || resource === 'analyses') {
			void queryClient.invalidateQueries({ queryKey: ['analyses'] });
			void queryClient.invalidateQueries({ queryKey: ['analysis'] });
		} else if (resource === 'datasource' || resource === 'datasources') {
			void queryClient.invalidateQueries({ queryKey: ['datasources'] });
		} else if (resource === 'healthcheck' || resource === 'healthchecks') {
			void queryClient.invalidateQueries({ queryKey: ['healthchecks'] });
		} else if (resource === 'scheduler' || resource === 'schedules') {
			void queryClient.invalidateQueries({ queryKey: ['schedules'] });
		}
	}

	onMount(() => {
		window.addEventListener('chat:ui_patch', onPatch);
		return () => window.removeEventListener('chat:ui_patch', onPatch);
	});

	// Overlay config for the panel — two-level escape: close sub-panels first, then close panel.
	const chatOverlayConfig = $derived<OverlayConfig>({
		onEscape: () => {
			if (configOpen || toolsOpen || sessionsOpen) {
				configOpen = false;
				toolsOpen = false;
				sessionsOpen = false;
				return;
			}
			chatStore.close();
		}
	});

	function onGlobalKey(e: KeyboardEvent) {
		if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
			e.preventDefault();
			if (!chatStore.open) {
				void chatStore.open_panel();
			}
			focusInput();
		}
	}
</script>

<svelte:window onkeydown={onGlobalKey} />

<ConfirmDialog
	show={chatStore.confirmClose}
	heading="Close Session"
	message="This will end the current chat session. Message history will be lost."
	confirmText="Close"
	cancelText="Keep"
	onConfirm={() => void chatStore.closeSession()}
	onCancel={() => chatStore.cancelCloseSession()}
/>

{#if chatStore.open}
	<div
		id="chat-panel"
		class={css({
			position: 'fixed',
			bottom: '0',
			right: '4',
			display: 'flex',
			flexDirection: 'column',
			backgroundColor: 'bg.panel',
			borderWidth: '1',
			borderTopRadius: 'lg',
			boxShadow: 'lg',
			zIndex: 'overlay',
			userSelect: layout.isResizing ? 'none' : 'auto',
			overflow: 'hidden'
		})}
		style:width="{layout.panelWidth}px"
		style:height="{layout.activeHeight}px"
		use:overlayStack.action={chatOverlayConfig}
		use:focusPanel
	>
		<!-- Corner resize handle (top-left) -->
		<div
			role="separator"
			tabindex="-1"
			class={css({
				position: 'absolute',
				top: '0',
				left: '0',
				width: '12px',
				height: '12px',
				cursor: 'nwse-resize',
				zIndex: '1',
				borderTopLeftRadius: 'lg',
				touchAction: 'none'
			})}
			onpointerdown={(event) => layout.startCornerResize(event)}
		></div>

		<!-- Left edge resize handle -->
		<div
			role="separator"
			aria-orientation="vertical"
			tabindex="-1"
			class={css({
				position: 'absolute',
				top: '12px',
				left: '0',
				bottom: '0',
				width: '6px',
				cursor: 'ew-resize',
				zIndex: '1',
				touchAction: 'none',
				_hover: { backgroundColor: 'border.primary' }
			})}
			onpointerdown={(event) => layout.startWidthResize(event)}
		></div>

		<!-- Top edge resize handle -->
		<div
			role="separator"
			aria-orientation="horizontal"
			tabindex="-1"
			class={css({
				position: 'relative',
				height: '6px',
				cursor: 'ns-resize',
				flexShrink: '0',
				borderTopRadius: 'lg',
				touchAction: 'none',
				_before: {
					content: '""',
					position: 'absolute',
					top: '-4px',
					left: '12px',
					right: '0',
					bottom: '0'
				},
				_hover: { backgroundColor: 'border.primary' }
			})}
			onpointerdown={(event) => layout.startHeightResize(event)}
		></div>

		<!-- Header -->
		<div
			class={css({
				borderBottomWidth: '1',
				flexShrink: '0'
			})}
		>
			<!-- Top row: mode toggle + action buttons -->
			<div
				class={css({
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'space-between',
					paddingX: '3',
					paddingY: '1.5'
				})}
			>
				<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
					<!-- Mode toggle -->
					<div
						class={css({
							display: 'flex',
							borderRadius: 'md',
							overflow: 'hidden',
							borderWidth: '1',
							flexShrink: '0'
						})}
					>
						<button
							class={css({
								display: 'flex',
								alignItems: 'center',
								gap: '1',
								paddingX: '2',
								paddingY: '1',
								fontSize: '11px',
								fontWeight: 'medium',
								border: 'none',
								cursor: 'pointer',
								backgroundColor: chatStore.mode === 'plan' ? 'bg.accent' : 'transparent',
								color: chatStore.mode === 'plan' ? 'fg.primary' : 'fg.muted',
								_hover: chatStore.mode === 'plan' ? {} : { backgroundColor: 'bg.tertiary' }
							})}
							onclick={() => chatStore.setMode('plan')}
							type="button"
							title="Plan mode: read-only, proposes plans"
						>
							<Eye size={10} />
							Plan
						</button>
						<button
							class={css({
								display: 'flex',
								alignItems: 'center',
								gap: '1',
								paddingX: '2',
								paddingY: '1',
								fontSize: '11px',
								fontWeight: 'medium',
								border: 'none',
								borderLeftWidth: '1',
								cursor: 'pointer',
								backgroundColor: chatStore.mode === 'execute' ? 'fg.primary' : 'transparent',
								color: chatStore.mode === 'execute' ? 'bg.panel' : 'fg.muted',
								_hover: chatStore.mode === 'execute' ? {} : { backgroundColor: 'bg.tertiary' }
							})}
							onclick={() => chatStore.setMode('execute')}
							type="button"
							title="Execute mode: full access, auto-executes"
						>
							<Play size={10} />
							Execute
						</button>
					</div>
					{#if chatStore.loading}
						<LoaderCircle
							size={10}
							class={css({ animation: 'spin 1s linear infinite', flexShrink: '0' })}
						/>
					{/if}
				</div>
				<div class={css({ display: 'flex', gap: '0.5', flexShrink: '0' })}>
					<button
						class={[
							css({
								display: 'inline-flex',
								alignItems: 'center',
								justifyContent: 'center',
								borderWidth: '1',
								backgroundColor: 'bg.primary',
								padding: '2',
								color: 'fg.secondary',
								transitionProperty: 'color, background-color, border-color, opacity',
								transitionDuration: '160ms',
								transitionTimingFunction: 'ease',
								_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' }
							}),
							toolsOpen && css({ color: 'fg.primary' })
						]}
						onclick={() => togglePanel('tools')}
						title="Tools"
						aria-label="Tools"
					>
						<Wrench size={13} />
					</button>
					<button
						class={[
							css({
								display: 'inline-flex',
								alignItems: 'center',
								justifyContent: 'center',
								borderWidth: '1',
								backgroundColor: 'bg.primary',
								padding: '2',
								color: 'fg.secondary',
								transitionProperty: 'color, background-color, border-color, opacity',
								transitionDuration: '160ms',
								transitionTimingFunction: 'ease',
								_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' }
							}),
							sessionsOpen && css({ color: 'fg.primary' })
						]}
						onclick={() => togglePanel('sessions')}
						title="Sessions"
						aria-label="Sessions"
					>
						<History size={13} />
					</button>
					<button
						class={[
							css({
								display: 'inline-flex',
								alignItems: 'center',
								justifyContent: 'center',
								borderWidth: '1',
								backgroundColor: 'bg.primary',
								padding: '2',
								color: 'fg.secondary',
								transitionProperty: 'color, background-color, border-color, opacity',
								transitionDuration: '160ms',
								transitionTimingFunction: 'ease',
								_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' }
							}),
							configOpen && css({ color: 'fg.primary' })
						]}
						onclick={() => togglePanel('config')}
						title="Configure"
						aria-label="Configure"
					>
						<Settings2 size={13} />
					</button>
					<button
						class={iconButton()}
						onclick={() => (layout.maximized = !layout.maximized)}
						title={layout.maximized ? 'Minimize' : 'Expand'}
						aria-label={layout.maximized ? 'Minimize' : 'Expand'}
					>
						{#if layout.maximized}<Minimize2 size={13} />{:else}<Maximize2 size={13} />{/if}
					</button>
					<button
						class={iconButton()}
						onclick={() => void chatStore.newSession()}
						title="New session"
						aria-label="New session"
					>
						<Plus size={13} />
					</button>
					<button
						class={iconButton()}
						onclick={() => chatStore.close()}
						title="Close chat (Esc)"
						aria-label="Close chat"
					>
						<X size={13} />
					</button>
				</div>
			</div>
		</div>

		<!-- Config panel -->
		{#if configOpen}
			<ChatConfigPanel maximized={layout.maximized} onClose={() => (configOpen = false)} />
		{/if}

		{#if toolsOpen}
			<ChatToolsPanel maximized={layout.maximized} />
		{/if}

		{#if sessionsOpen}
			<ChatSessionsPanel maximized={layout.maximized} />
		{/if}

		{#if layout.maximized || !anyPanelOpen}
			<ChatMessages
				bind:this={messagesRef}
				onSendPrompt={(text) => void handleSendPrompt(text)}
				onFocusInput={focusInput}
			/>
		{/if}

		<ChatComposer
			bind:inputValue
			bind:textareaEl={inputEl}
			onSend={handleSend}
			onStop={stopGeneration}
		/>
	</div>
{/if}

<style>
	/* Typing indicator dots */
	:global(.chat-dot) {
		display: inline-block;
		width: 5px;
		height: 5px;
		border-radius: 50%;
		background-color: var(--colors-fg-muted);
		animation: chat-bounce 1.4s ease-in-out infinite;
	}
	:global(.chat-dot-1) {
		animation-delay: 0s;
	}
	:global(.chat-dot-2) {
		animation-delay: 0.2s;
	}
	:global(.chat-dot-3) {
		animation-delay: 0.4s;
	}
	@keyframes chat-bounce {
		0%,
		60%,
		100% {
			transform: translateY(0);
			opacity: 0.4;
		}
		30% {
			transform: translateY(-3px);
			opacity: 1;
		}
	}

	/* Markdown styling for assistant messages */
	:global(.chat-markdown p) {
		margin: 0 0 0.4em 0;
	}
	:global(.chat-markdown p:last-child) {
		margin-bottom: 0;
	}
	:global(.chat-markdown code) {
		font-family: 'JetBrains Mono', 'Fira Code', monospace;
		font-size: 0.85em;
		padding: 0.1em 0.3em;
		border-radius: 3px;
		background-color: var(--colors-bg-tertiary);
	}
	:global(.chat-markdown pre) {
		margin: 0.4em 0;
		padding: 0.6em;
		border-radius: 4px;
		background-color: var(--colors-bg-tertiary);
		overflow-x: auto;
		position: relative;
	}
	:global(.chat-markdown pre code) {
		padding: 0;
		background: none;
		font-size: 0.8em;
		line-height: 1.4;
	}
	:global(.chat-markdown ul),
	:global(.chat-markdown ol) {
		margin: 0.2em 0;
		padding-left: 1.4em;
	}
	:global(.chat-markdown li) {
		margin: 0.1em 0;
	}
	:global(.chat-markdown h1),
	:global(.chat-markdown h2),
	:global(.chat-markdown h3) {
		margin: 0.4em 0 0.2em 0;
		font-size: 1em;
		font-weight: 600;
	}
	:global(.chat-markdown blockquote) {
		margin: 0.4em 0;
		padding-left: 0.6em;
		border-left: 2px solid var(--colors-border-primary);
		color: var(--colors-fg-muted);
	}
	:global(.chat-markdown a) {
		color: var(--colors-accent-primary);
		text-decoration: underline;
	}
	:global(.chat-markdown table) {
		border-collapse: collapse;
		margin: 0.4em 0;
		font-size: 0.85em;
		width: 100%;
	}
	:global(.chat-markdown th),
	:global(.chat-markdown td) {
		border: 1px solid var(--colors-border-default);
		padding: 0.3em 0.4em;
		text-align: left;
	}
	:global(.chat-markdown th) {
		background-color: var(--colors-bg-subtle);
		font-weight: 600;
	}

	/* Copy button visibility on hover */
	:global(.chat-copy-btn) {
		transition: opacity 150ms ease;
	}

	/* Timestamp shown on hover of message group */
	:global(.chat-ts) {
		transition:
			opacity 150ms ease,
			height 150ms ease;
	}
	:global(.chat-msg-enter:hover .chat-ts) {
		opacity: 1 !important;
		height: auto !important;
		overflow: visible !important;
	}

	/* Code block copy button */
	:global(.code-copy-btn) {
		position: absolute;
		top: 4px;
		right: 4px;
		padding: 3px;
		border: none;
		border-radius: 3px;
		background-color: transparent;
		color: var(--colors-fg-muted);
		cursor: pointer;
		opacity: 0;
		transition: opacity 150ms ease;
		line-height: 1;
	}
	:global(.chat-markdown pre:hover .code-copy-btn) {
		opacity: 1;
	}
	:global(.code-copy-btn:hover) {
		color: var(--colors-fg-primary);
		background-color: var(--colors-bg-subtle);
	}

	/* Subtle slide-in for new messages */
	@keyframes chat-msg-in {
		from {
			opacity: 0;
			transform: translateY(4px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}
	:global(.chat-msg-enter) {
		animation: chat-msg-in 150ms ease-out;
	}
</style>
