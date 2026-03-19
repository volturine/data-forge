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
		model: 'llama2',
		input_columns: [],
		output_column: 'ai_result',
		prompt_template: 'Classify this text: {{text}}',
		batch_size: 10,
		endpoint_url: '',
		api_key: '',
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
			<option value="openai">OpenAI (Cloud)</option>
		</select>
	</div>

	<div class={css({ marginBottom: '5' })}>
		<label class={label()} for="ai-model">Model</label>
		<input
			id="ai-model"
			type="text"
			class={input()}
			bind:value={config.model}
			placeholder={config.provider === 'openai' ? 'gpt-4o' : 'llama2'}
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
				: 'http://localhost:11434'}
		/>
	</div>

	{#if config.provider === 'openai'}
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

	<div class={css({ marginBottom: '0' })}>
		<label class={label()} for="ai-prompt">Prompt Template</label>
		<textarea id="ai-prompt" class={input()} rows="4" bind:value={config.prompt_template}
		></textarea>
		<span class={css({ marginTop: '1', display: 'block', fontSize: 'xs', color: 'fg.muted' })}>
			{placeholderHint}
		</span>
	</div>
</div>
