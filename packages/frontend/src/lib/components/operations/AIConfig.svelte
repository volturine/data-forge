<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import type { AIConfigData } from '$lib/types/operation-config';
	import MultiSelectColumnDropdown from '$lib/components/common/MultiSelectColumnDropdown.svelte';
	import { css, label, stepConfig, input } from '$lib/styles/panda';

	interface Props {
		config?: AIConfigData;
		schema: Schema;
	}

	const defaultConfig: AIConfigData = {
		provider: 'ollama',
		model: 'llama3.2',
		input_columns: [],
		output_column: 'ai_result',
		error_column: 'ai_error',
		prompt_template: 'Classify this text: {{text}}',
		batch_size: 10,
		max_retries: 3,
		rate_limit_rpm: null,
		endpoint_url: '',
		api_key: '',
		temperature: 0.7,
		max_tokens: null,
		request_options: null
	};

	let { config = $bindable(defaultConfig), schema }: Props = $props();

	function handleColumnsChange(columns: string[]) {
		config.input_columns = columns;
	}

	const inputColumns = $derived(Array.isArray(config?.input_columns) ? config.input_columns : []);

	const placeholderHint = $derived.by(() => {
		if (inputColumns.length === 0) return 'Select column(s), then use {{column_name}} in prompt';
		if (inputColumns.length === 1)
			return `Use {{text}} or {{${inputColumns[0]}}} to reference the column value`;
		return `Use {{${inputColumns.join('}}, {{')}}} in prompt template`;
	});
</script>

<div class={stepConfig()} role="region" aria-label="AI configuration">
	<div class={css({ marginBottom: '5' })}>
		<label class={label()} for="ai-provider">Provider</label>
		<select id="ai-provider" class={input()} bind:value={config.provider}>
			<option value="ollama">Ollama (Local)</option>
			<option value="openai">OpenAI</option>
			<option value="openrouter">OpenRouter</option>
			<option value="huggingface">Hugging Face API</option>
		</select>
	</div>

	<div class={css({ marginBottom: '5' })}>
		<label class={label()} for="ai-model">Model</label>
		<input
			id="ai-model"
			type="text"
			class={input()}
			bind:value={config.model}
			placeholder={config.provider === 'openai'
				? 'gpt-4o-mini'
				: config.provider === 'openrouter'
					? 'openai/gpt-4o-mini'
					: config.provider === 'huggingface'
						? 'google/flan-t5-base'
						: 'llama3.2'}
		/>
	</div>

	<div class={css({ marginBottom: '5' })}>
		<label class={label()} for="ai-endpoint">Endpoint URL</label>
		<input
			id="ai-endpoint"
			type="text"
			class={input()}
			bind:value={config.endpoint_url}
			placeholder={config.provider === 'openai'
				? 'https://api.openai.com'
				: config.provider === 'huggingface'
					? 'https://api-inference.huggingface.co'
					: 'http://localhost:11434'}
		/>
	</div>

	{#if config.provider === 'openai' || config.provider === 'openrouter' || config.provider === 'huggingface'}
		<div class={css({ marginBottom: '5' })}>
			<label class={label()} for="ai-api-key">API Key</label>
			<input
				id="ai-api-key"
				type="password"
				class={input()}
				bind:value={config.api_key}
				placeholder="sk-..."
			/>
		</div>
	{/if}

	<!-- svelte-ignore a11y_label_has_associated_control -->
	<div class={css({ marginBottom: '5' })}>
		<label class={label()}>Input Column(s)</label>
		<MultiSelectColumnDropdown
			{schema}
			value={inputColumns}
			onChange={handleColumnsChange}
			placeholder="Select column(s)..."
			showSelectAll={false}
		/>
	</div>

	<div class={css({ marginBottom: '5' })}>
		<label class={label()} for="ai-output">Output Column</label>
		<input
			id="ai-output"
			type="text"
			class={input()}
			bind:value={config.output_column}
			placeholder="ai_result"
		/>
	</div>

	<div class={css({ marginBottom: '5' })}>
		<label class={label()} for="ai-error-output">Error Column</label>
		<input
			id="ai-error-output"
			type="text"
			class={input()}
			bind:value={config.error_column}
			placeholder="ai_error"
		/>
	</div>

	<div class={css({ marginBottom: '0' })}>
		<label class={label()} for="ai-prompt">Prompt Template</label>
		<textarea id="ai-prompt" class={input()} rows="4" bind:value={config.prompt_template}
		></textarea>
		<span class={css({ marginTop: '1', display: 'block', fontSize: 'xs', color: 'fg.muted' })}>
			{placeholderHint}
		</span>
	</div>

	<div class={css({ marginTop: '5', display: 'grid', gap: '3', gridTemplateColumns: '1fr 1fr' })}>
		<div>
			<label class={label()} for="ai-batch-size">Batch Size</label>
			<input
				id="ai-batch-size"
				type="number"
				min="1"
				class={input()}
				bind:value={config.batch_size}
			/>
		</div>
		<div>
			<label class={label()} for="ai-max-retries">Max Retries</label>
			<input
				id="ai-max-retries"
				type="number"
				min="0"
				class={input()}
				bind:value={config.max_retries}
			/>
		</div>
		<div>
			<label class={label()} for="ai-rate-limit">Rate Limit (RPM)</label>
			<input
				id="ai-rate-limit"
				type="number"
				min="1"
				class={input()}
				value={config.rate_limit_rpm ?? ''}
				oninput={(event) => {
					const next = Number.parseInt((event.currentTarget as HTMLInputElement).value, 10);
					config.rate_limit_rpm = Number.isNaN(next) ? null : next;
				}}
			/>
		</div>
		<div>
			<label class={label()} for="ai-temperature">Temperature</label>
			<input
				id="ai-temperature"
				type="number"
				step="0.1"
				min="0"
				max="2"
				class={input()}
				bind:value={config.temperature}
			/>
		</div>
		<div>
			<label class={label()} for="ai-max-tokens">Max Tokens</label>
			<input
				id="ai-max-tokens"
				type="number"
				min="1"
				class={input()}
				value={config.max_tokens ?? ''}
				oninput={(event) => {
					const next = Number.parseInt((event.currentTarget as HTMLInputElement).value, 10);
					config.max_tokens = Number.isNaN(next) ? null : next;
				}}
			/>
		</div>
	</div>
</div>
