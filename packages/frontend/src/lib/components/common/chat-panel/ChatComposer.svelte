<script lang="ts">
	import { ChevronDown, LoaderCircle, Send, Square, Timer, WifiOff } from '@lucide/svelte';
	import { css, iconButton } from '$lib/styles/panda';
	import { chatStore } from '$lib/stores/chat.svelte';
	import type { ChatProvider } from '$lib/stores/chat.svelte';
	import { formatTokens } from '$lib/chat/presentation';

	interface Props {
		inputValue?: string;
		textareaEl?: HTMLTextAreaElement;
		onSend: () => Promise<void>;
		onStop: () => Promise<void>;
	}

	let {
		inputValue = $bindable(''),
		textareaEl = $bindable(undefined),
		onSend,
		onStop
	}: Props = $props();

	let modelPickerOpen = $state(false);
	let modelPickerSearch = $state('');

	function autoResize() {
		if (!textareaEl) return;
		textareaEl.style.height = 'auto';
		textareaEl.style.height = Math.min(textareaEl.scrollHeight, 120) + 'px';
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			void onSend();
		}
	}

	function handlePaste() {
		requestAnimationFrame(autoResize);
	}

	function pickModel(id: string) {
		modelPickerSearch = '';
		modelPickerOpen = false;
		void chatStore.changeModel(id);
	}

	function toggleModelPicker() {
		modelPickerOpen = !modelPickerOpen;
		modelPickerSearch = '';
		if (modelPickerOpen && chatStore.models.length === 0) {
			void chatStore.loadModels();
		}
	}

	const pickerModels = $derived(
		modelPickerSearch
			? chatStore.models.filter(
					(m) =>
						m.id.toLowerCase().includes(modelPickerSearch.toLowerCase()) ||
						m.name.toLowerCase().includes(modelPickerSearch.toLowerCase())
				)
			: chatStore.models
	);

	const connectionColor = $derived(
		chatStore.connection === 'connected'
			? 'fg.success'
			: chatStore.connection === 'reconnecting'
				? 'fg.warning'
				: 'fg.muted'
	);

	const connectionLabel = $derived(
		chatStore.connection === 'connected'
			? 'Connected'
			: chatStore.connection === 'reconnecting'
				? `Reconnecting\u2026`
				: 'Disconnected'
	);

	const lastPromptTokens = $derived(chatStore.lastTurnUsage?.prompt_tokens ?? 0);
	const contextPct = $derived(
		chatStore.contextLimit > 0
			? Math.min(100, (lastPromptTokens / chatStore.contextLimit) * 100)
			: 0
	);

	const contextBarColor = $derived(
		contextPct > 90 ? 'fg.error' : contextPct > 70 ? 'fg.warning' : 'accent.primary'
	);

	const inputPlaceholder = $derived(
		!chatStore.configured
			? 'Loading\u2026'
			: chatStore.mode === 'plan'
				? 'Describe what you want to analyze\u2026'
				: 'Tell me what to do\u2026'
	);
</script>

<!-- Input area -->
<div
	class={css({
		display: 'flex',
		flexDirection: 'column',
		gap: '1',
		padding: '2',
		paddingX: '3',
		paddingBottom: '2',
		borderTopWidth: '1',
		flexShrink: '0'
	})}
>
	<!-- Model picker + indicators row -->
	<div
		class={css({
			display: 'flex',
			alignItems: 'center',
			gap: '2',
			position: 'relative',
			fontSize: '10px',
			fontFamily: 'mono',
			color: 'fg.muted'
		})}
	>
		<select
			class={css({
				borderWidth: '1',
				backgroundColor: 'bg.panel',
				color: 'fg.muted',
				fontSize: '10px',
				fontFamily: 'mono',
				paddingX: '1',
				paddingY: '0.5',
				height: '20px',
				flexShrink: '0'
			})}
			value={chatStore.provider}
			onchange={(event) => {
				const provider = (event.currentTarget as HTMLSelectElement).value as ChatProvider;
				chatStore.setProvider(provider);
				if (chatStore.models.length === 0) {
					void chatStore.loadModels();
				}
			}}
			title="Chat provider"
		>
			<option value="openrouter">OpenRouter</option>
			<option value="openai">OpenAI</option>
			<option value="ollama">Ollama</option>
		</select>

		<button
			class={css({
				display: 'flex',
				alignItems: 'center',
				gap: '1',
				border: 'none',
				background: 'none',
				padding: '0',
				cursor: 'pointer',
				color: 'fg.muted',
				fontSize: '10px',
				fontFamily: 'mono',
				flexShrink: '0',
				_hover: { color: 'fg.primary' }
			})}
			onclick={toggleModelPicker}
			type="button"
			title={chatStore.model}
		>
			{chatStore.modelDisplayName}
			<ChevronDown size={8} />
		</button>
		{#if chatStore.sessionId}
			<span
				class={css({
					display: 'inline-block',
					height: 'dot',
					width: 'dot',
					flexShrink: '0',
					borderRadius: 'full',
					backgroundColor: connectionColor
				})}
				title={connectionLabel}
			></span>
			{#if chatStore.connection === 'disconnected'}
				<button
					class={css({
						display: 'flex',
						alignItems: 'center',
						gap: '0.5',
						border: 'none',
						background: 'none',
						padding: '0',
						cursor: 'pointer',
						color: 'fg.muted',
						fontSize: '10px',
						fontFamily: 'mono',
						flexShrink: '0',
						_hover: { color: 'fg.primary' }
					})}
					onclick={() => chatStore.reconnectNow()}
					type="button"
					title="Reconnect now"
				>
					<WifiOff size={8} />
					Reconnect
				</button>
			{/if}
			{#if chatStore.currentTurn > 0}
				<span
					class={css({
						display: 'flex',
						alignItems: 'center',
						gap: '0.5',
						flexShrink: '0',
						color: 'accent.primary',
						fontSize: '10px',
						fontFamily: 'mono'
					})}
					title={chatStore.maxTurns != null
						? `Agent turn ${chatStore.currentTurn} of ${chatStore.maxTurns}`
						: `Agent turn ${chatStore.currentTurn}`}
				>
					<Timer size={8} />
					Turn {chatStore.currentTurn}{chatStore.maxTurns != null ? `/${chatStore.maxTurns}` : ''}
				</span>
			{/if}
		{/if}
		{#if chatStore.sessionId && chatStore.sessionUsage.total_tokens > 0}
			<span
				class={css({ flexShrink: '0' })}
				title={`Prompt: ${formatTokens(lastPromptTokens)} | Completion: ${formatTokens(chatStore.lastTurnUsage?.completion_tokens ?? 0)} | Session: ${formatTokens(chatStore.sessionUsage.prompt_tokens)} in / ${formatTokens(chatStore.sessionUsage.completion_tokens)} out / ${formatTokens(chatStore.sessionUsage.total_tokens)} total`}
			>
				{formatTokens(lastPromptTokens)}{chatStore.contextLimit > 0
					? ` / ${formatTokens(chatStore.contextLimit)}`
					: ''}
			</span>
			{#if chatStore.contextLimit > 0}
				<div
					class={css({
						flex: '1',
						minWidth: '20px',
						height: '3px',
						backgroundColor: 'bg.secondary',
						borderRadius: 'full',
						overflow: 'hidden'
					})}
					title={`${Math.round(contextPct)}% context used`}
				>
					<div
						class={css({
							height: '100%',
							borderRadius: 'full',
							backgroundColor: contextBarColor
						})}
						style="width: {contextPct}%"
					></div>
				</div>
				<span
					class={css({ flexShrink: '0', color: contextPct > 70 ? contextBarColor : 'fg.muted' })}
				>
					{Math.round(contextPct)}%
				</span>
			{/if}
		{/if}
		{#if modelPickerOpen}
			<div
				class={css({
					position: 'absolute',
					bottom: '100%',
					left: '0',
					minWidth: '260px',
					maxHeight: '200px',
					overflowY: 'auto',
					backgroundColor: 'bg.panel',
					borderWidth: '1',
					borderRadius: 'sm',
					zIndex: 'dropdown',
					boxShadow: 'md',
					marginBottom: '4px'
				})}
			>
				<input
					class={css({
						width: 'full',
						color: 'fg.primary',
						paddingX: '3.5',
						paddingY: '2.25',
						transitionProperty: 'border-color',
						transitionDuration: '160ms',
						transitionTimingFunction: 'ease',
						_focus: { outline: 'none' },
						_focusVisible: { borderColor: 'border.accent' },
						_disabled: {
							opacity: '0.5',
							cursor: 'not-allowed',
							backgroundColor: 'bg.tertiary'
						},
						_placeholder: { color: 'fg.muted' },
						borderRadius: '0',
						borderWidth: '0',
						borderBottomWidth: '1',
						fontSize: 'xs'
					})}
					type="text"
					bind:value={modelPickerSearch}
					placeholder="Search models\u2026"
				/>
				{#if chatStore.modelsLoading}
					<div
						class={css({
							padding: '2',
							textAlign: 'center',
							fontSize: 'xs',
							color: 'fg.muted'
						})}
					>
						<LoaderCircle
							size={12}
							class={css({ animation: 'spin 1s linear infinite', display: 'inline' })}
						/> Loading\u2026
					</div>
				{:else if pickerModels.length === 0}
					<div class={css({ padding: '2', fontSize: 'xs', color: 'fg.muted' })}>
						{chatStore.models.length === 0 ? 'No models loaded' : 'No matches'}
					</div>
				{:else}
					{#each pickerModels.slice(0, 30) as m (m.id)}
						<button
							class={css({
								display: 'flex',
								flexDirection: 'column',
								gap: '0',
								width: '100%',
								textAlign: 'left',
								padding: '1.5',
								paddingX: '2',
								border: 'none',
								backgroundColor: m.id === chatStore.model ? 'bg.accent' : 'transparent',
								color: m.id === chatStore.model ? 'fg.primary' : 'fg.primary',
								cursor: 'pointer',
								_hover: { backgroundColor: 'bg.hover' }
							})}
							onclick={() => pickModel(m.id)}
							type="button"
						>
							<span class={css({ fontSize: 'xs' })}>{m.name}</span>
							<span
								class={css({
									fontSize: '9px',
									color: m.id === chatStore.model ? 'fg.primary' : 'fg.muted',
									fontFamily: 'mono'
								})}
							>
								{m.id}{m.context_length > 0 ? ` \u00b7 ${formatTokens(m.context_length)} ctx` : ''}
							</span>
						</button>
					{/each}
				{/if}
			</div>
		{/if}
	</div>
	<!-- Textarea + send button -->
	<div class={css({ display: 'flex', gap: '2', alignItems: 'flex-end' })}>
		<textarea
			class={css({
				width: 'full',
				color: 'fg.primary',
				backgroundColor: 'bg.primary',
				borderWidth: '1',
				borderRadius: '0',
				paddingX: '3.5',
				paddingY: '2.25',
				transitionProperty: 'border-color',
				transitionDuration: '160ms',
				transitionTimingFunction: 'ease',
				_focus: { outline: 'none' },
				_focusVisible: { borderColor: 'border.accent' },
				_disabled: { opacity: '0.5', cursor: 'not-allowed', backgroundColor: 'bg.tertiary' },
				_placeholder: { color: 'fg.muted' },
				flex: '1',
				resize: 'none',
				minHeight: '34px',
				maxHeight: '120px',
				fontSize: 'sm'
			})}
			bind:value={inputValue}
			bind:this={textareaEl}
			onkeydown={handleKeydown}
			oninput={autoResize}
			onpaste={handlePaste}
			placeholder={inputPlaceholder}
			disabled={!chatStore.configured || chatStore.loading}
			rows={1}></textarea>
		{#if chatStore.loading}
			<button
				class={iconButton()}
				onclick={() => void onStop()}
				title="Stop generating"
				aria-label="Stop generating"
			>
				<Square size={13} />
			</button>
		{:else}
			<button
				class={iconButton()}
				onclick={() => void onSend()}
				disabled={!inputValue.trim() || !chatStore.configured}
				title="Send message"
				aria-label="Send message"
			>
				<Send size={14} />
			</button>
		{/if}
	</div>
</div>
