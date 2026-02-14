<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import type { NotificationConfigData } from '$lib/utils/step-config-defaults';
	import MultiSelectColumnDropdown from '$lib/components/common/MultiSelectColumnDropdown.svelte';

	interface Props {
		config?: NotificationConfigData;
		schema: Schema;
		configFlags?: { smtpEnabled: boolean; telegramEnabled: boolean };
	}

	const defaultConfig: NotificationConfigData = {
		method: 'email',
		recipient: '',
		bot_token: '',
		input_columns: [],
		output_column: 'notification_status',
		message_template: '{{message}}',
		subject_template: 'Notification',
		batch_size: 10,
		timeout_seconds: 20
	};

	let {
		config = $bindable(defaultConfig),
		schema,
		configFlags = { smtpEnabled: true, telegramEnabled: true }
	}: Props = $props();

	const canEmail = $derived(configFlags.smtpEnabled);
	const canTelegram = $derived(configFlags.telegramEnabled);
	const isReady = $derived(
		(config.method === 'email' && canEmail) || (config.method === 'telegram' && canTelegram)
	);

	function handleColumnsChange(columns: string[]) {
		config.input_columns = columns;
	}

	const placeholderHint = $derived.by(() => {
		const cols = config.input_columns;
		if (cols.length === 0) return 'Select column(s), then use {{column_name}} in template';
		if (cols.length === 1) return `Use {{${cols[0]}}} to reference the column value`;
		return `Use {{${cols.join('}}, {{')}}} in template`;
	});
</script>

<div class="config-panel" role="region" aria-label="Notification configuration">
	<h3>Notification (UDF)</h3>

	{#if !isReady}
		<div class="rounded-sm border border-tertiary bg-bg-secondary p-3 text-sm text-fg-tertiary">
			Configure SMTP or Telegram in global settings first.
		</div>
	{/if}

	<div class="form-group mb-4">
		<label for="notify-method">Method</label>
		<select id="notify-method" bind:value={config.method}>
			<option value="email" disabled={!canEmail}>Email (SMTP)</option>
			<option value="telegram" disabled={!canTelegram}>Telegram</option>
		</select>
	</div>

	<div class="form-group mb-4">
		<label for="notify-recipient">
			{config.method === 'email' ? 'Email Address' : 'Chat ID(s)'}
		</label>
		<input
			id="notify-recipient"
			type="text"
			bind:value={config.recipient}
			placeholder={config.method === 'email' ? 'user@example.com' : '123456789, 987654321'}
		/>
		{#if config.method === 'telegram'}
			<span class="mt-1 block text-xs text-fg-muted">Comma-separated for multiple</span>
		{/if}
	</div>

	<!-- svelte-ignore a11y_label_has_associated_control -->
	<div class="form-group mb-4">
		<label>Input Column(s)</label>
		<MultiSelectColumnDropdown
			{schema}
			value={config.input_columns}
			onChange={handleColumnsChange}
			placeholder="Select column(s)..."
			showSelectAll={false}
		/>
	</div>

	<div class="form-group mb-4">
		<label for="notify-output">Output Column</label>
		<input
			id="notify-output"
			type="text"
			bind:value={config.output_column}
			placeholder="notification_status"
		/>
	</div>

	{#if config.method === 'email'}
		<div class="form-group mb-4">
			<label for="notify-subject">Subject Template</label>
			<input id="notify-subject" type="text" bind:value={config.subject_template} />
		</div>
	{/if}

	<div class="form-group mb-0">
		<label for="notify-message">Message Template</label>
		<textarea id="notify-message" rows="4" bind:value={config.message_template}></textarea>
		<span class="hint mt-1 block text-xs text-fg-muted">
			{placeholderHint}
		</span>
	</div>
</div>
