<script lang="ts">
	import { CheckCircle, XCircle, Save, Loader2 } from 'lucide-svelte';
	import { getSettings, updateSettings, isMasked, MASKED_PLACEHOLDER } from '$lib/api/settings';
	import type { AppSettings } from '$lib/api/settings';
	import { listAIModels, testAIConnection } from '$lib/api/ai';
	import { css, input, label } from '$lib/styles/panda';

	let loading = $state(true);
	let saving = $state(false);
	let testingProvider = $state<string | null>(null);
	let feedback = $state<{ type: 'success' | 'error'; message: string } | null>(null);

	// OpenRouter
	let openrouter_api_key = $state('');
	let openrouter_default_model = $state('');
	let openrouter_api_key_dirty = $state(false);

	// OpenAI
	let openai_api_key = $state('');
	let openai_endpoint_url = $state('https://api.openai.com');
	let openai_default_model = $state('gpt-4o-mini');
	let openai_organization_id = $state('');
	let openai_api_key_dirty = $state(false);

	// Ollama
	let ollama_endpoint_url = $state('http://localhost:11434');
	let ollama_default_model = $state('llama3.2');

	// Hugging Face
	let huggingface_api_token = $state('');
	let huggingface_default_model = $state('google/flan-t5-base');
	let huggingface_api_token_dirty = $state(false);

	// Network: load settings on mount.
	$effect(() => {
		loading = true;
		feedback = null;
		openrouter_api_key_dirty = false;
		openai_api_key_dirty = false;
		huggingface_api_token_dirty = false;
		let aborted = false;
		getSettings().match(
			(s) => {
				if (aborted) return;
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

	async function save() {
		saving = true;
		feedback = null;
		const payload: Partial<AppSettings> = {
			openrouter_default_model,
			openai_endpoint_url,
			openai_default_model,
			openai_organization_id,
			ollama_endpoint_url,
			ollama_default_model,
			huggingface_default_model
		};
		if (openrouter_api_key_dirty) payload.openrouter_api_key = openrouter_api_key;
		if (openai_api_key_dirty) payload.openai_api_key = openai_api_key;
		if (huggingface_api_token_dirty) payload.huggingface_api_token = huggingface_api_token;
		const result = await updateSettings(payload);
		result.match(
			() => {
				feedback = { type: 'success', message: 'AI provider settings saved' };
			},
			(err) => {
				feedback = { type: 'error', message: err.message };
			}
		);
		saving = false;
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

	const feedbackStyle = (type: 'success' | 'error') =>
		css({
			display: 'flex',
			alignItems: 'center',
			gap: '2',
			borderWidth: '1',
			padding: '2',
			fontSize: 'sm',
			...(type === 'success'
				? {
						borderColor: 'border.success',
						backgroundColor: 'bg.success',
						color: 'fg.success'
					}
				: { borderColor: 'border.error', backgroundColor: 'bg.error', color: 'fg.error' })
		});
</script>

{#if loading}
	<div
		class={css({
			display: 'flex',
			alignItems: 'center',
			justifyContent: 'center',
			gap: '2',
			padding: '8',
			fontSize: 'sm',
			color: 'fg.muted'
		})}
	>
		<Loader2 size={14} class={css({ animation: 'spin 1s linear infinite' })} />
		Loading AI provider settings…
	</div>
{:else}
	<div class={css({ display: 'flex', flexDirection: 'column', gap: '6' })}>
		{#if feedback}
			<div class={feedbackStyle(feedback.type)}>
				{#if feedback.type === 'success'}
					<CheckCircle size={14} />
				{:else}
					<XCircle size={14} />
				{/if}
				{feedback.message}
			</div>
		{/if}

		<div
			class={css({
				backgroundColor: 'bg.panel',
				borderWidth: '1',
				padding: '6',
				display: 'flex',
				flexDirection: 'column',
				gap: '4'
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
				backgroundColor: 'bg.panel',
				borderWidth: '1',
				padding: '6',
				display: 'flex',
				flexDirection: 'column',
				gap: '4'
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
					gap: '3'
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
				<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>Organization ID (optional)</span
				>
				<input type="text" class={input()} bind:value={openai_organization_id} />
			</label>
		</div>

		<div
			class={css({
				backgroundColor: 'bg.panel',
				borderWidth: '1',
				padding: '6',
				display: 'flex',
				flexDirection: 'column',
				gap: '4'
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
					gap: '3'
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
				backgroundColor: 'bg.panel',
				borderWidth: '1',
				padding: '6',
				display: 'flex',
				flexDirection: 'column',
				gap: '4'
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

		<div class={css({ display: 'flex', justifyContent: 'flex-end' })}>
			<button
				class={css({
					display: 'flex',
					cursor: 'pointer',
					alignItems: 'center',
					gap: '1.5',
					border: 'none',
					paddingX: '4',
					paddingY: '2',
					fontSize: 'sm',
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
					<Loader2 size={14} class={css({ animation: 'spin 1s linear infinite' })} />
				{:else}
					<Save size={14} />
				{/if}
				Save
			</button>
		</div>
	</div>
{/if}
