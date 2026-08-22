<script lang="ts">
	import { Search, LoaderCircle } from '@lucide/svelte';
	import { css, button, input, label } from '$lib/styles/panda';
	import { chatStore } from '$lib/stores/chat.svelte';

	interface Props {
		maximized: boolean;
		onClose: () => void;
	}

	let { maximized, onClose }: Props = $props();

	// Seeded once at panel open — the component is created fresh by the parent's {#if}
	let apiKeyDraft = $state(chatStore.apiKey);
	let providerDraft = $state(chatStore.provider);
	let modelDraft = $state(chatStore.model);
	let systemPromptDraft = $state(chatStore.systemPrompt);
	let modelSearch = $state('');

	async function saveConfig() {
		chatStore.setProvider(providerDraft as 'openrouter' | 'openai' | 'ollama');
		chatStore.model = modelDraft;
		chatStore.systemPrompt = systemPromptDraft;
		await chatStore.configure(apiKeyDraft);
		onClose();
	}

	function handleLoadModels() {
		chatStore.setProvider(providerDraft as 'openrouter' | 'openai' | 'ollama');
		chatStore.apiKey = apiKeyDraft;
		void chatStore.loadModels();
	}

	function selectModel(id: string) {
		modelDraft = id;
		modelSearch = '';
	}

	const filteredModels = $derived(
		modelSearch
			? chatStore.models.filter(
					(m) =>
						m.id.toLowerCase().includes(modelSearch.toLowerCase()) ||
						m.name.toLowerCase().includes(modelSearch.toLowerCase())
				)
			: chatStore.models
	);
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
	<div>
		<label class={label()} for="chat-provider">Provider</label>
		<select
			id="chat-provider"
			class={input()}
			bind:value={providerDraft}
			disabled={!!chatStore.sessionId}
		>
			<option value="openrouter">OpenRouter</option>
			<option value="openai">OpenAI</option>
			<option value="ollama">Ollama</option>
		</select>
	</div>

	<div>
		<label class={label()} for="chat-key">API Key</label>
		<div class={css({ display: 'flex', gap: '1' })}>
			<input
				id="chat-key"
				class={[
					css({
						width: 'full',
						fontSize: 'sm2',
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
						_disabled: {
							opacity: '0.5',
							cursor: 'not-allowed',
							backgroundColor: 'bg.tertiary'
						},
						_placeholder: { color: 'fg.muted' }
					}),
					css({ flex: '1' })
				]}
				type="password"
				bind:value={apiKeyDraft}
				placeholder="sk-or-… (uses global if empty)"
				disabled={!!chatStore.sessionId}
			/>
			<button
				class={button({ variant: 'ghost', size: 'sm' })}
				onclick={handleLoadModels}
				disabled={chatStore.modelsLoading || !!chatStore.sessionId}
				title="Fetch models"
				type="button"
			>
				{#if chatStore.modelsLoading}
					<LoaderCircle size={12} class={css({ animation: 'spin 1s linear infinite' })} />
				{:else}
					<Search size={12} />
				{/if}
			</button>
		</div>
	</div>

	<div>
		<label class={label()} for="chat-model">Model</label>
		{#if chatStore.models.length > 0}
			<div class={css({ position: 'relative' })}>
				<input
					id="chat-model-search"
					class={input()}
					type="text"
					bind:value={modelSearch}
					placeholder="Search models…"
					disabled={!!chatStore.sessionId}
				/>
				{#if modelSearch && filteredModels.length > 0}
					<div
						class={css({
							position: 'absolute',
							top: '100%',
							left: '0',
							right: '0',
							maxHeight: '150px',
							overflowY: 'auto',
							backgroundColor: 'bg.panel',
							borderWidth: '1',
							borderRadius: 'sm',
							zIndex: 'dropdown',
							boxShadow: 'md'
						})}
					>
						{#each filteredModels.slice(0, 20) as m (m.id)}
							<button
								class={css({
									display: 'block',
									width: '100%',
									textAlign: 'left',
									padding: '1.5',
									paddingX: '2',
									fontSize: 'xs',
									border: 'none',
									backgroundColor: m.id === modelDraft ? 'bg.accent' : 'transparent',
									color: m.id === modelDraft ? 'fg.primary' : 'fg.primary',
									cursor: 'pointer',
									_hover: { backgroundColor: 'bg.hover' }
								})}
								onclick={() => selectModel(m.id)}
								type="button"
							>
								{m.name}
								<span class={css({ color: 'fg.muted', fontFamily: 'mono', fontSize: 'xs' })}
									>{m.id}</span
								>
							</button>
						{/each}
					</div>
				{/if}
			</div>
			<div
				class={css({
					fontSize: 'xs',
					color: 'fg.muted',
					marginTop: '1',
					fontFamily: 'mono',
					wordBreak: 'break-all'
				})}
			>
				{modelDraft}
			</div>
		{:else}
			<input
				id="chat-model"
				class={input()}
				type="text"
				bind:value={modelDraft}
				placeholder={modelDraft || 'openai/gpt-4o-mini'}
				disabled
			/>
			<span class={css({ fontSize: 'xs', color: 'fg.muted', marginTop: '0.5' })}>
				Click <Search size={10} class={css({ display: 'inline' })} /> to load available models
			</span>
		{/if}
	</div>

	<div>
		<label class={label()} for="chat-system-prompt">System Prompt (override)</label>
		<textarea
			id="chat-system-prompt"
			class={css({
				width: 'full',
				fontSize: 'sm2',
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
				resize: 'none',
				minHeight: '48px',
				maxHeight: '100px'
			})}
			bind:value={systemPromptDraft}
			placeholder="Leave empty to use mode default ({chatStore.mode})"
			rows={2}
			disabled={!!chatStore.sessionId}
		></textarea>
	</div>

	<button
		class={button({ variant: 'primary' })}
		onclick={saveConfig}
		disabled={!!chatStore.sessionId}
	>
		{chatStore.sessionId ? 'Active session — close to reconfigure' : 'Apply'}
	</button>
</div>
