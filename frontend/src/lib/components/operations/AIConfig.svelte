<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import { createQuery } from '@tanstack/svelte-query';
	import { listAIModels, testAIConnection } from '$lib/api/ai';
	import type { AIConnectionResult } from '$lib/api/ai';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';
	import { Wifi, WifiOff, LoaderCircle } from 'lucide-svelte';

	type AIConfigData = {
		provider: 'ollama' | 'openai';
		model: string;
		input_column: string;
		output_column: string;
		prompt_template: string;
		batch_size: number;
		endpoint_url?: string | null;
		api_key?: string | null;
		request_options?: string | null;
	};

	interface Props {
		config?: Record<string, unknown>;
		schema: Schema;
	}

	const defaultConfig: AIConfigData = {
		provider: 'ollama',
		model: 'llama2',
		input_column: '',
		output_column: 'ai_result',
		prompt_template: 'Classify this text: {{text}}',
		batch_size: 10,
		endpoint_url: null,
		api_key: null,
		request_options: null
	};

	let { config = $bindable(defaultConfig), schema }: Props = $props();
	let aiConfig = $derived.by(() => config as AIConfigData);

	const modelsQuery = createQuery(() => ({
		queryKey: ['ai-models', aiConfig.provider, aiConfig.endpoint_url, aiConfig.api_key],
		queryFn: async () => {
			const result = await listAIModels(aiConfig.provider, aiConfig.endpoint_url, aiConfig.api_key);
			if (result.isOk()) return result.value;
			return [];
		},
		staleTime: 30_000
	}));

	const ollamaFallback = [
		'llama2',
		'llama3',
		'codellama',
		'mistral',
		'gemma',
		'phi',
		'neural-chat'
	];
	const openaiFallback = ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo', 'gpt-3.5-turbo'];

	const models = $derived.by(() => {
		const fetched = modelsQuery.data ?? [];
		if (fetched.length > 0) return fetched.map((m) => m.name).filter(Boolean);
		return aiConfig.provider === 'ollama' ? ollamaFallback : openaiFallback;
	});

	let testing = $state(false);
	let connectionResult = $state<AIConnectionResult | null>(null);

	async function handleTest() {
		testing = true;
		connectionResult = null;
		const result = await testAIConnection(
			aiConfig.provider,
			aiConfig.endpoint_url,
			aiConfig.api_key
		);
		if (result.isOk()) {
			connectionResult = result.value;
		} else {
			connectionResult = { ok: false, detail: result.error.message };
		}
		testing = false;
	}

	function handleInputColumnChange(value: string) {
		aiConfig.input_column = value;
	}
</script>

<div class="config-panel" role="region" aria-label="AI configuration">
	<h3>AI</h3>

	<div class="form-group mb-4">
		<label for="ai-provider">Provider</label>
		<select id="ai-provider" bind:value={aiConfig.provider}>
			<option value="ollama">Ollama (Local)</option>
			<option value="openai">OpenAI (Cloud)</option>
		</select>
	</div>

	<div class="form-group mb-4">
		<label for="ai-model">Model</label>
		<select id="ai-model" bind:value={aiConfig.model}>
			{#each models as model (model)}
				<option value={model}>{model}</option>
			{/each}
		</select>
		{#if modelsQuery.isFetching}
			<span class="mt-1 flex items-center gap-1 text-xs text-fg-muted">
				<LoaderCircle class="h-3 w-3 animate-spin" />
				Loading models...
			</span>
		{/if}
	</div>

	<div class="form-group mb-4">
		<label for="ai-endpoint">Endpoint URL</label>
		<div class="flex gap-2">
			<input
				id="ai-endpoint"
				type="text"
				class="flex-1"
				bind:value={aiConfig.endpoint_url}
				placeholder={aiConfig.provider === 'openai'
					? 'https://api.openai.com'
					: 'http://localhost:11434'}
			/>
			<button
				type="button"
				class="cursor-pointer border border-tertiary bg-secondary px-3 py-1.5 text-xs font-mono text-fg-secondary transition-colors hover:bg-tertiary"
				onclick={handleTest}
				disabled={testing}
			>
				{#if testing}
					<LoaderCircle class="h-3.5 w-3.5 animate-spin" />
				{:else}
					Test
				{/if}
			</button>
		</div>
		{#if connectionResult}
			<span
				class="mt-1 flex items-center gap-1 text-xs"
				class:text-accent-primary={connectionResult.ok}
				class:text-red-400={!connectionResult.ok}
			>
				{#if connectionResult.ok}
					<Wifi class="h-3 w-3" />
				{:else}
					<WifiOff class="h-3 w-3" />
				{/if}
				{connectionResult.detail}
			</span>
		{/if}
	</div>

	{#if aiConfig.provider === 'openai'}
		<div class="form-group mb-4">
			<label for="ai-api-key">API Key</label>
			<input id="ai-api-key" type="password" bind:value={aiConfig.api_key} placeholder="sk-..." />
		</div>
	{/if}

	<!-- svelte-ignore a11y_label_has_associated_control -->
	<div class="form-group mb-4">
		<label>Input Column</label>
		<ColumnDropdown
			{schema}
			value={aiConfig.input_column}
			onChange={handleInputColumnChange}
			placeholder="Select text column..."
			filter={(col) =>
				col.dtype === 'Utf8' ||
				col.dtype === 'String' ||
				col.dtype.startsWith('Utf8') ||
				col.dtype.startsWith('String')}
		/>
	</div>

	<div class="form-group mb-4">
		<label for="ai-output">Output Column</label>
		<input id="ai-output" type="text" bind:value={aiConfig.output_column} placeholder="ai_result" />
	</div>

	<div class="form-group mb-4">
		<label for="ai-prompt">Prompt Template</label>
		<textarea id="ai-prompt" rows="4" bind:value={aiConfig.prompt_template}></textarea>
		<span class="hint mt-1 block text-xs text-fg-muted">
			Use {'{{text}}'} to reference the input column value
		</span>
	</div>

	<div class="form-group mb-4">
		<label for="ai-options">Request Options (JSON)</label>
		<textarea id="ai-options" rows="3" bind:value={aiConfig.request_options}></textarea>
		<span class="hint mt-1 block text-xs text-fg-muted">
			Example: {`{"temperature": 0.2}`}
		</span>
	</div>

	<div class="form-group mb-0">
		<label for="ai-batch">Batch Size</label>
		<input id="ai-batch" type="number" min="1" max="100" bind:value={aiConfig.batch_size} />
	</div>
</div>
