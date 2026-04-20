<script lang="ts">
	import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
	import {
		X,
		Mail,
		MessageCircle,
		Database,
		ChevronDown,
		CircleCheckBig,
		CircleX,
		Send,
		Save,
		LoaderCircle,
		Trash2
	} from 'lucide-svelte';
	import {
		getSettings,
		updateSettings,
		testSmtp,
		getBotStatus,
		getSubscribers,
		deleteSubscriber,
		isMasked,
		MASKED_PLACEHOLDER
	} from '$lib/api/settings';
	import type { AppSettings } from '$lib/api/settings';
	import { listAIModels, testAIConnection } from '$lib/api/ai';
	import { configStore } from '$lib/stores/config.svelte';
	import BaseModal from '$lib/components/ui/BaseModal.svelte';
	import PanelHeader from '$lib/components/ui/PanelHeader.svelte';
	import SectionHeader from '$lib/components/ui/SectionHeader.svelte';
	import { css, input, label } from '$lib/styles/panda';

	interface Props {
		open: boolean;
	}

	let { open = $bindable() }: Props = $props();

	const queryClient = useQueryClient();

	// Form state
	let smtp_host = $state('');
	let smtp_port = $state(587);
	let smtp_user = $state('');
	let smtp_password = $state('');
	let telegram_bot_token = $state('');
	let telegram_bot_enabled = $state(false);
	let openrouter_api_key = $state('');
	let openrouter_default_model = $state('');
	let openai_api_key = $state('');
	let openai_endpoint_url = $state('https://api.openai.com');
	let openai_default_model = $state('gpt-4o-mini');
	let openai_organization_id = $state('');
	let ollama_endpoint_url = $state('http://localhost:11434');
	let ollama_default_model = $state('llama3.2');
	let huggingface_api_token = $state('');
	let huggingface_default_model = $state('google/flan-t5-base');
	let idb = $state(false);

	// Track whether user explicitly changed secret fields
	let smtp_password_dirty = $state(false);
	let telegram_bot_token_dirty = $state(false);
	let openrouter_api_key_dirty = $state(false);
	let openai_api_key_dirty = $state(false);
	let huggingface_api_token_dirty = $state(false);

	// UI state
	let loading = $state(false);
	let saving = $state(false);
	let testingSmtp = $state(false);
	let testingProvider = $state<string | null>(null);
	let smtpTestTo = $state('');
	let feedback = $state<{ type: 'success' | 'error'; message: string } | null>(null);
	let aiProvidersCollapsed = $state(true);
	let smtpCollapsed = $state(true);
	let telegramCollapsed = $state(true);
	let debugCollapsed = $state(true);

	// Network: $derived can't fetch settings on open.
	$effect(() => {
		if (!open) return;
		loading = true;
		feedback = null;
		aiProvidersCollapsed = true;
		smtpCollapsed = true;
		telegramCollapsed = true;
		debugCollapsed = true;
		smtp_password_dirty = false;
		telegram_bot_token_dirty = false;
		openrouter_api_key_dirty = false;
		openai_api_key_dirty = false;
		huggingface_api_token_dirty = false;
		let aborted = false;
		getSettings().match(
			(s) => {
				if (aborted) return;
				smtp_host = s.smtp_host;
				smtp_port = s.smtp_port;
				smtp_user = s.smtp_user;
				smtp_password = isMasked(s.smtp_password) ? '' : s.smtp_password;
				telegram_bot_token = isMasked(s.telegram_bot_token) ? '' : s.telegram_bot_token;
				telegram_bot_enabled = s.telegram_bot_enabled;
				openrouter_api_key = isMasked(s.openrouter_api_key) ? '' : s.openrouter_api_key;
				openrouter_default_model = s.openrouter_default_model;
				openai_api_key = isMasked(s.openai_api_key) ? '' : s.openai_api_key;
				openai_endpoint_url = s.openai_endpoint_url;
				openai_default_model = s.openai_default_model;
				openai_organization_id = s.openai_organization_id;
				ollama_endpoint_url = s.ollama_endpoint_url;
				ollama_default_model = s.ollama_default_model;
				huggingface_api_token = isMasked(s.huggingface_api_token) ? '' : s.huggingface_api_token;
				huggingface_default_model = s.huggingface_default_model;
				idb = s.public_idb_debug;
				loading = false;
			},
			() => {
				if (aborted) return;
				loading = false;
			}
		);
		return () => {
			aborted = true;
		};
	});

	// Telegram bot status query
	const statusQuery = createQuery(() => ({
		queryKey: ['telegram-status'],
		queryFn: async () => {
			const result = await getBotStatus();
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		staleTime: 10_000,
		enabled: open
	}));

	// Telegram subscribers query
	const subscribersQuery = createQuery(() => ({
		queryKey: ['telegram-subscribers'],
		queryFn: async () => {
			const result = await getSubscribers();
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		staleTime: 10_000,
		enabled: open
	}));

	// Delete subscriber mutation
	const deleteMut = createMutation(() => ({
		mutationFn: async (id: number) => {
			const result = await deleteSubscriber(id);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ['telegram-status'] });
			queryClient.invalidateQueries({ queryKey: ['telegram-subscribers'] });
		}
	}));

	const botRunning = $derived(statusQuery.data?.running ?? false);
	const subscribers = $derived(subscribersQuery.data ?? []);

	async function save() {
		saving = true;
		feedback = null;
		const payload: Partial<AppSettings> = {
			smtp_host,
			smtp_port,
			smtp_user,
			telegram_bot_enabled,
			openrouter_default_model,
			openai_endpoint_url,
			openai_default_model,
			openai_organization_id,
			ollama_endpoint_url,
			ollama_default_model,
			huggingface_default_model,
			public_idb_debug: idb
		};
		if (smtp_password_dirty) payload.smtp_password = smtp_password;
		if (telegram_bot_token_dirty) payload.telegram_bot_token = telegram_bot_token;
		if (openrouter_api_key_dirty) payload.openrouter_api_key = openrouter_api_key;
		if (openai_api_key_dirty) payload.openai_api_key = openai_api_key;
		if (huggingface_api_token_dirty) payload.huggingface_api_token = huggingface_api_token;
		const result = await updateSettings(payload);
		result.match(
			() => {
				feedback = { type: 'success', message: 'Settings saved' };
				// Refresh frontend config so smtp_enabled / telegram_enabled update
				configStore['fetched'] = false;
				configStore.fetch();
				// Refresh bot status since saving restarts/stops the bot
				queryClient.invalidateQueries({ queryKey: ['telegram-status'] });
				queryClient.invalidateQueries({ queryKey: ['telegram-subscribers'] });
			},
			(err) => {
				feedback = { type: 'error', message: err.message };
			}
		);
		saving = false;
	}

	async function handleTestSmtp() {
		if (!smtpTestTo) return;
		testingSmtp = true;
		feedback = null;
		const result = await testSmtp(smtpTestTo);
		result.match(
			(r) => {
				feedback = { type: r.success ? 'success' : 'error', message: r.message };
			},
			(err) => {
				feedback = { type: 'error', message: err.message };
			}
		);
		testingSmtp = false;
	}

	async function handleTestAIProvider(
		provider: 'openrouter' | 'openai' | 'ollama' | 'huggingface'
	) {
		testingProvider = provider;
		feedback = null;
		const endpoint =
			provider === 'openai'
				? openai_endpoint_url
				: provider === 'ollama'
					? ollama_endpoint_url
					: provider === 'huggingface'
						? 'https://api-inference.huggingface.co'
						: null;
		const apiKey =
			provider === 'openrouter'
				? openrouter_api_key || null
				: provider === 'openai'
					? openai_api_key || null
					: provider === 'huggingface'
						? huggingface_api_token || null
						: null;
		const organizationId = provider === 'openai' ? openai_organization_id || null : null;

		const testResult = await testAIConnection(provider, endpoint, apiKey, organizationId);
		const modelsResult = await listAIModels(provider, endpoint, apiKey, organizationId);
		testResult.match(
			(result) => {
				const modelsCount = modelsResult.isOk() ? modelsResult.value.length : 0;
				const modelsText = modelsCount > 0 ? ` (${modelsCount} model(s) listed)` : '';
				feedback = {
					type: result.ok ? 'success' : 'error',
					message: `${provider}: ${result.detail}${modelsText}`
				};
			},
			(err) => {
				feedback = { type: 'error', message: err.message };
			}
		);
		testingProvider = null;
	}
</script>

<BaseModal
	{open}
	onClose={() => (open = false)}
	closeOnEscape={true}
	closeOnBackdrop={true}
	panelClass={css({
		width: '100%',
		maxWidth: 'modalSm',
		maxHeight: '90vh',
		overflowY: 'auto',
		borderWidth: '1',
		backgroundColor: 'bg.primary',
		outline: 'none'
	})}
	ariaLabelledby="settings-title"
	{content}
/>

{#snippet content()}
	<PanelHeader>
		{#snippet title()}
			<h2 id="settings-title" class={css({ margin: '0', fontSize: 'sm', fontWeight: 'semibold' })}>
				Settings
			</h2>
		{/snippet}
		{#snippet actions()}
			<button
				class={css({
					display: 'flex',
					cursor: 'pointer',
					alignItems: 'center',
					justifyContent: 'center',
					border: 'none',
					backgroundColor: 'transparent',
					padding: '1',
					color: 'fg.muted',
					_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' }
				})}
				onclick={() => (open = false)}
				aria-label="Close settings"
				type="button"
			>
				<X size={16} />
			</button>
		{/snippet}
	</PanelHeader>

	{#if loading}
		<div
			class={css({
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'center',
				gap: '2',
				padding: '8',
				fontSize: 'xs',
				color: 'fg.muted'
			})}
		>
			<LoaderCircle size={14} class={css({ animation: 'spin 1s linear infinite' })} />
			Loading settings...
		</div>
	{:else}
		<div class={css({ display: 'flex', flexDirection: 'column', gap: '4', padding: '4' })}>
			{#if feedback}
				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						gap: '2',
						borderWidth: '1',
						padding: '2',
						fontSize: 'xs',
						...(feedback.type === 'success'
							? {
									borderColor: 'border.success',
									backgroundColor: 'bg.success',
									color: 'fg.success'
								}
							: { borderColor: 'border.error', backgroundColor: 'bg.error', color: 'fg.error' })
					})}
				>
					{#if feedback.type === 'success'}
						<CircleCheckBig size={12} />
					{:else}
						<CircleX size={12} />
					{/if}
					{feedback.message}
				</div>
			{/if}

			<button
				class={css({
					display: 'flex',
					width: '100%',
					cursor: 'pointer',
					alignItems: 'center',
					justifyContent: 'space-between',
					border: 'none',
					backgroundColor: 'transparent',
					padding: '0',
					textAlign: 'left',
					transition: 'color 150ms',
					_hover: { color: 'fg.primary' }
				})}
				type="button"
				aria-expanded={!aiProvidersCollapsed}
				aria-controls="settings-ai-providers"
				onclick={() => (aiProvidersCollapsed = !aiProvidersCollapsed)}
			>
				<span class={css({ display: 'inline-flex', alignItems: 'center', gap: '1.5' })}>
					<SectionHeader>AI Providers</SectionHeader>
				</span>
				<ChevronDown
					size={14}
					class={css(
						{ transition: 'transform 150ms' },
						aiProvidersCollapsed && { transform: 'rotate(-90deg)' }
					)}
				/>
			</button>

			<div
				id="settings-ai-providers"
				hidden={aiProvidersCollapsed}
				aria-hidden={aiProvidersCollapsed}
				class={css(
					{ display: 'flex', flexDirection: 'column', gap: '4' },
					aiProvidersCollapsed && { display: 'none' }
				)}
			>
				<div
					class={css({
						display: 'flex',
						flexDirection: 'column',
						gap: '2',
						borderWidth: '1',
						padding: '3'
					})}
				>
					<div
						class={css({
							display: 'flex',
							alignItems: 'center',
							justifyContent: 'space-between'
						})}
					>
						<span class={css({ fontSize: 'sm', fontWeight: 'medium' })}>OpenRouter</span>
						<button
							class={css({
								borderWidth: '1',
								paddingX: '2',
								paddingY: '1',
								fontSize: 'xs',
								_disabled: { opacity: '0.5', cursor: 'not-allowed' }
							})}
							onclick={() => void handleTestAIProvider('openrouter')}
							disabled={testingProvider === 'openrouter'}
							aria-label="Test OpenRouter"
							type="button"
						>
							{testingProvider === 'openrouter' ? 'Testing…' : 'Test'}
						</button>
					</div>
					<label class={label({ variant: 'wrapper' })}>
						<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>API key</span>
						<input
							type="password"
							class={input()}
							bind:value={openrouter_api_key}
							oninput={() => (openrouter_api_key_dirty = true)}
							placeholder={MASKED_PLACEHOLDER}
						/>
					</label>
					<label class={label({ variant: 'wrapper' })}>
						<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>Default model</span>
						<input
							type="text"
							class={input()}
							bind:value={openrouter_default_model}
							placeholder="openai/gpt-4o-mini"
						/>
					</label>
				</div>

				<div
					class={css({
						display: 'flex',
						flexDirection: 'column',
						gap: '2',
						borderWidth: '1',
						padding: '3'
					})}
				>
					<div
						class={css({
							display: 'flex',
							alignItems: 'center',
							justifyContent: 'space-between'
						})}
					>
						<span class={css({ fontSize: 'sm', fontWeight: 'medium' })}>OpenAI</span>
						<button
							class={css({
								borderWidth: '1',
								paddingX: '2',
								paddingY: '1',
								fontSize: 'xs',
								_disabled: { opacity: '0.5', cursor: 'not-allowed' }
							})}
							onclick={() => void handleTestAIProvider('openai')}
							disabled={testingProvider === 'openai'}
							aria-label="Test OpenAI"
							type="button"
						>
							{testingProvider === 'openai' ? 'Testing…' : 'Test'}
						</button>
					</div>
					<label class={label({ variant: 'wrapper' })}>
						<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>API key</span>
						<input
							type="password"
							class={input()}
							bind:value={openai_api_key}
							oninput={() => (openai_api_key_dirty = true)}
							placeholder={MASKED_PLACEHOLDER}
						/>
					</label>
					<div
						class={css({
							display: 'grid',
							gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
							gap: '2'
						})}
					>
						<label class={label({ variant: 'wrapper' })}>
							<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>Endpoint URL</span>
							<input type="text" class={input()} bind:value={openai_endpoint_url} />
						</label>
						<label class={label({ variant: 'wrapper' })}>
							<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>Default model</span>
							<input type="text" class={input()} bind:value={openai_default_model} />
						</label>
					</div>
					<label class={label({ variant: 'wrapper' })}>
						<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}
							>Organization ID (optional)</span
						>
						<input type="text" class={input()} bind:value={openai_organization_id} />
					</label>
				</div>

				<div
					class={css({
						display: 'flex',
						flexDirection: 'column',
						gap: '2',
						borderWidth: '1',
						padding: '3'
					})}
				>
					<div
						class={css({
							display: 'flex',
							alignItems: 'center',
							justifyContent: 'space-between'
						})}
					>
						<span class={css({ fontSize: 'sm', fontWeight: 'medium' })}>Ollama</span>
						<button
							class={css({
								borderWidth: '1',
								paddingX: '2',
								paddingY: '1',
								fontSize: 'xs',
								_disabled: { opacity: '0.5', cursor: 'not-allowed' }
							})}
							onclick={() => void handleTestAIProvider('ollama')}
							disabled={testingProvider === 'ollama'}
							aria-label="Test Ollama"
							type="button"
						>
							{testingProvider === 'ollama' ? 'Testing…' : 'Test'}
						</button>
					</div>
					<div
						class={css({
							display: 'grid',
							gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
							gap: '2'
						})}
					>
						<label class={label({ variant: 'wrapper' })}>
							<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>Endpoint URL</span>
							<input type="text" class={input()} bind:value={ollama_endpoint_url} />
						</label>
						<label class={label({ variant: 'wrapper' })}>
							<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>Default model</span>
							<input type="text" class={input()} bind:value={ollama_default_model} />
						</label>
					</div>
				</div>

				<div
					class={css({
						display: 'flex',
						flexDirection: 'column',
						gap: '2',
						borderWidth: '1',
						padding: '3'
					})}
				>
					<div
						class={css({
							display: 'flex',
							alignItems: 'center',
							justifyContent: 'space-between'
						})}
					>
						<span class={css({ fontSize: 'sm', fontWeight: 'medium' })}>Hugging Face</span>
						<button
							class={css({
								borderWidth: '1',
								paddingX: '2',
								paddingY: '1',
								fontSize: 'xs',
								_disabled: { opacity: '0.5', cursor: 'not-allowed' }
							})}
							onclick={() => void handleTestAIProvider('huggingface')}
							disabled={testingProvider === 'huggingface'}
							aria-label="Test Hugging Face"
							type="button"
						>
							{testingProvider === 'huggingface' ? 'Testing…' : 'Test'}
						</button>
					</div>
					<label class={label({ variant: 'wrapper' })}>
						<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>API token</span>
						<input
							type="password"
							class={input()}
							bind:value={huggingface_api_token}
							oninput={() => (huggingface_api_token_dirty = true)}
							placeholder={MASKED_PLACEHOLDER}
						/>
					</label>
					<label class={label({ variant: 'wrapper' })}>
						<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>Default model</span>
						<input type="text" class={input()} bind:value={huggingface_default_model} />
					</label>
				</div>
			</div>

			<div
				class={css({
					borderBottomWidth: '1'
				})}
			></div>

			<button
				class={css({
					display: 'flex',
					width: '100%',
					cursor: 'pointer',
					alignItems: 'center',
					justifyContent: 'space-between',
					border: 'none',
					backgroundColor: 'transparent',
					padding: '0',
					textAlign: 'left',
					transition: 'color 150ms',
					_hover: { color: 'fg.primary' }
				})}
				type="button"
				aria-expanded={!smtpCollapsed}
				aria-controls="settings-smtp"
				onclick={() => (smtpCollapsed = !smtpCollapsed)}
			>
				<span class={css({ display: 'inline-flex', alignItems: 'center', gap: '1.5' })}>
					<Mail size={12} />
					<SectionHeader>SMTP</SectionHeader>
				</span>
				<ChevronDown
					size={14}
					class={css(
						{ transition: 'transform 150ms' },
						smtpCollapsed && { transform: 'rotate(-90deg)' }
					)}
				/>
			</button>

			<div
				id="settings-smtp"
				hidden={smtpCollapsed}
				aria-hidden={smtpCollapsed}
				class={css(
					{ display: 'flex', flexDirection: 'column', gap: '2' },
					smtpCollapsed && { display: 'none' }
				)}
			>
				<div
					class={css({
						display: 'grid',
						gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
						gap: '2'
					})}
				>
					<label class={label({ variant: 'wrapper' })}>
						<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>Host</span>
						<input
							type="text"
							class={input()}
							id="smtp-host"
							bind:value={smtp_host}
							placeholder="smtp.example.com"
						/>
					</label>
					<label class={label({ variant: 'wrapper' })}>
						<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>Port</span>
						<input type="number" class={input()} id="smtp-port" bind:value={smtp_port} />
					</label>
				</div>

				<div
					class={css({
						display: 'grid',
						gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
						gap: '2'
					})}
				>
					<label class={label({ variant: 'wrapper' })}>
						<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>User</span>
						<input
							type="text"
							class={input()}
							id="smtp-user"
							bind:value={smtp_user}
							placeholder="user@example.com"
						/>
					</label>
					<label class={label({ variant: 'wrapper' })}>
						<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>Password</span>
						<input
							type="password"
							class={input()}
							id="smtp-password"
							bind:value={smtp_password}
							oninput={() => (smtp_password_dirty = true)}
							placeholder={MASKED_PLACEHOLDER}
						/>
					</label>
				</div>

				<div class={css({ display: 'flex', alignItems: 'flex-end', gap: '2' })}>
					<label
						class={css({
							display: 'flex',
							flexDirection: 'column',
							gap: '1',
							fontSize: 'xs2',
							fontWeight: 'semibold',
							color: 'fg.muted',
							marginBottom: '0',
							textTransform: 'none',
							letterSpacing: 'normal',
							flex: '1'
						})}
					>
						<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>Test recipient</span>
						<input
							type="email"
							class={input()}
							id="smtp-test-to"
							data-testid="settings-smtp-test-recipient"
							bind:value={smtpTestTo}
							placeholder="test@example.com"
						/>
					</label>
					<button
						class={css({
							display: 'flex',
							flexShrink: '0',
							cursor: 'pointer',
							alignItems: 'center',
							gap: '1',
							borderWidth: '1',
							paddingX: '3',
							paddingY: '1.5',
							fontSize: 'xs',
							fontWeight: 'medium',
							backgroundColor: 'bg.tertiary',
							color: 'fg.secondary',
							_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' },
							_disabled: { cursor: 'not-allowed', opacity: 0.5 }
						})}
						onclick={handleTestSmtp}
						disabled={testingSmtp || !smtpTestTo}
						aria-label="Test SMTP"
						data-testid="settings-smtp-test-button"
						type="button"
					>
						{#if testingSmtp}
							<LoaderCircle size={12} class={css({ animation: 'spin 1s linear infinite' })} />
						{:else}
							<Send size={12} />
						{/if}
						Test
					</button>
				</div>
			</div>

			<div
				class={css({
					borderBottomWidth: '1'
				})}
			></div>

			<button
				class={css({
					display: 'flex',
					width: '100%',
					cursor: 'pointer',
					alignItems: 'center',
					justifyContent: 'space-between',
					border: 'none',
					backgroundColor: 'transparent',
					padding: '0',
					textAlign: 'left',
					transition: 'color 150ms',
					_hover: { color: 'fg.primary' }
				})}
				type="button"
				aria-expanded={!telegramCollapsed}
				aria-controls="settings-telegram"
				onclick={() => (telegramCollapsed = !telegramCollapsed)}
			>
				<span class={css({ display: 'inline-flex', alignItems: 'center', gap: '1.5' })}>
					<MessageCircle size={12} />
					<SectionHeader>Telegram</SectionHeader>
				</span>
				<span class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
					{#if statusQuery.data}
						<span
							class={css({
								display: 'inline-block',
								height: 'dot',
								width: 'dot',
								flexShrink: '0',
								backgroundColor: botRunning ? 'fg.success' : 'fg.error'
							})}
							title={botRunning ? 'Bot running' : 'Bot stopped'}
						></span>
					{/if}
					<ChevronDown
						size={14}
						class={css(
							{ transition: 'transform 150ms' },
							telegramCollapsed && { transform: 'rotate(-90deg)' }
						)}
					/>
				</span>
			</button>

			<div
				id="settings-telegram"
				hidden={telegramCollapsed}
				aria-hidden={telegramCollapsed}
				class={css(
					{ display: 'flex', flexDirection: 'column', gap: '2' },
					telegramCollapsed && { display: 'none' }
				)}
			>
				<label class={label({ variant: 'wrapper' })}>
					<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>Bot token</span>
					<input
						type="password"
						class={input()}
						id="telegram-bot-token"
						bind:value={telegram_bot_token}
						oninput={() => (telegram_bot_token_dirty = true)}
						placeholder={MASKED_PLACEHOLDER}
					/>
				</label>

				<div
					class={css({ display: 'flex', alignItems: 'center', justifyContent: 'space-between' })}
				>
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '0.5' })}>
						<span class={css({ fontSize: 'sm', fontWeight: 'medium' })}>Enable Bot</span>
						<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>
							Start the Telegram bot listener on save
						</span>
					</div>
					<button
						class={css({
							position: 'relative',
							height: 'iconMd',
							width: 'rowXl',
							cursor: 'pointer',
							border: 'none',
							transition: 'background-color 150ms',
							backgroundColor: telegram_bot_enabled ? 'accent.primary' : 'bg.tertiary'
						})}
						onclick={() => (telegram_bot_enabled = !telegram_bot_enabled)}
						type="button"
						role="switch"
						aria-checked={telegram_bot_enabled}
						aria-label="Toggle Telegram bot"
					>
						<span
							class={css({
								position: 'absolute',
								top: '0.5',
								left: '0.5',
								height: 'iconSm',
								width: 'iconSm',
								backgroundColor: 'accent.primary',
								transition: 'transform 150ms',
								...(telegram_bot_enabled ? { transform: 'translateX(1rem)' } : {})
							})}
						></span>
					</button>
				</div>

				{#if statusQuery.data}
					<div
						class={css({
							display: 'flex',
							alignItems: 'center',
							justifyContent: 'space-between',
							borderWidth: '1',
							paddingX: '3',
							paddingY: '2',
							fontSize: 'xs',
							backgroundColor: 'bg.tertiary'
						})}
					>
						<span class={css({ display: 'flex', alignItems: 'center', gap: '1.5' })}>
							<span
								class={css({
									display: 'inline-block',
									height: 'barTall',
									width: 'barTall',
									flexShrink: '0',
									backgroundColor: botRunning ? 'fg.success' : 'fg.error'
								})}
							></span>
							<span class={css({ color: 'fg.secondary' })}>
								{botRunning ? 'Bot running' : 'Bot stopped'}
							</span>
						</span>
						<span class={css({ color: 'fg.tertiary' })}>
							{statusQuery.data.subscriber_count}
							{statusQuery.data.subscriber_count === 1 ? 'subscriber' : 'subscribers'}
						</span>
					</div>
				{/if}

				{#if subscribers.length > 0}
					<div
						class={css({
							display: 'flex',
							flexDirection: 'column',
							borderWidth: '1'
						})}
					>
						{#each subscribers as sub (sub.id)}
							<div
								class={css({
									display: 'flex',
									alignItems: 'center',
									justifyContent: 'space-between',
									borderBottomWidth: '1',
									paddingX: '3',
									paddingY: '2',
									fontSize: 'xs'
								})}
							>
								<div class={css({ display: 'flex', alignItems: 'center', gap: '2' })}>
									<span
										class={css({
											display: 'inline-block',
											height: 'barTall',
											width: 'barTall',
											flexShrink: '0',
											backgroundColor: sub.is_active ? 'fg.success' : 'bg.tertiary'
										})}
										title={sub.is_active ? 'Active' : 'Inactive'}
									></span>
									<span class={css({ fontWeight: 'medium' })}>{sub.title}</span>
									<span class={css({ color: 'fg.tertiary' })}>{sub.chat_id}</span>
								</div>
								<button
									class={css({
										display: 'flex',
										cursor: 'pointer',
										alignItems: 'center',
										justifyContent: 'center',
										border: 'none',
										backgroundColor: 'transparent',
										padding: '1',
										color: 'fg.tertiary',
										transition: 'color 150ms',
										_hover: { color: 'error' }
									})}
									onclick={() => deleteMut.mutate(sub.id)}
									disabled={deleteMut.isPending}
									type="button"
									title="Remove subscriber"
								>
									<Trash2 size={12} />
								</button>
							</div>
						{/each}
					</div>
				{:else if statusQuery.data && !subscribersQuery.isFetching}
					<p class={css({ margin: '0', fontSize: 'xs', color: 'fg.tertiary' })}>
						Subscribers appear here after users send /subscribe to your bot.
					</p>
				{/if}
			</div>

			<div
				class={css({
					borderBottomWidth: '1'
				})}
			></div>

			<button
				class={css({
					display: 'flex',
					width: '100%',
					cursor: 'pointer',
					alignItems: 'center',
					justifyContent: 'space-between',
					border: 'none',
					backgroundColor: 'transparent',
					padding: '0',
					textAlign: 'left',
					transition: 'color 150ms',
					_hover: { color: 'fg.primary' }
				})}
				type="button"
				aria-expanded={!debugCollapsed}
				aria-controls="settings-debug"
				onclick={() => (debugCollapsed = !debugCollapsed)}
			>
				<span class={css({ display: 'inline-flex', alignItems: 'center', gap: '1.5' })}>
					<Database size={12} />
					<SectionHeader>Debug</SectionHeader>
				</span>
				<ChevronDown
					size={14}
					class={css(
						{ transition: 'transform 150ms' },
						debugCollapsed && { transform: 'rotate(-90deg)' }
					)}
				/>
			</button>

			<div
				id="settings-debug"
				hidden={debugCollapsed}
				aria-hidden={debugCollapsed}
				class={debugCollapsed ? css({ display: 'none' }) : ''}
			>
				<div
					class={css({ display: 'flex', alignItems: 'center', justifyContent: 'space-between' })}
				>
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '0.5' })}>
						<span class={css({ fontSize: 'sm', fontWeight: 'medium' })}> IndexedDB Inspector </span>
						<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>
							Show cache debug button in header
						</span>
					</div>
					<button
						class={css({
							position: 'relative',
							height: 'iconMd',
							width: 'rowXl',
							cursor: 'pointer',
							border: 'none',
							transition: 'background-color 150ms',
							backgroundColor: idb ? 'accent.primary' : 'bg.tertiary'
						})}
						onclick={() => (idb = !idb)}
						type="button"
						role="switch"
						aria-checked={idb}
						aria-label="Toggle IndexedDB inspector"
					>
						<span
							class={css({
								position: 'absolute',
								top: '0.5',
								left: '0.5',
								height: 'iconSm',
								width: 'iconSm',
								backgroundColor: 'accent.primary',
								transition: 'transform 150ms',
								...(idb ? { transform: 'translateX(1rem)' } : {})
							})}
						></span>
					</button>
				</div>
			</div>
		</div>

		<div
			class={css({
				borderTopWidth: '1',
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'space-between',
				padding: '4'
			})}
		>
			<p class={css({ margin: '0', fontSize: 'xs', color: 'fg.tertiary' })}>
				Settings are stored in the database.
			</p>
			<button
				class={css({
					display: 'flex',
					cursor: 'pointer',
					alignItems: 'center',
					gap: '1.5',
					border: 'none',
					paddingX: '4',
					paddingY: '2',
					fontSize: 'xs',
					fontWeight: 'medium',
					backgroundColor: 'accent.primary',
					color: 'fg.inverse',
					_hover: { opacity: 0.9 },
					_disabled: { cursor: 'not-allowed', opacity: 0.5 }
				})}
				onclick={save}
				disabled={saving}
				type="button"
			>
				{#if saving}
					<LoaderCircle size={12} class={css({ animation: 'spin 1s linear infinite' })} />
				{:else}
					<Save size={12} />
				{/if}
				Save
			</button>
		</div>
	{/if}
{/snippet}
