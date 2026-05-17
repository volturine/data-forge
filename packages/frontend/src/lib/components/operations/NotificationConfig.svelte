<script lang="ts">
	import type { Schema } from '$lib/types/schema';
	import type { Subscriber } from '$lib/api/settings';
	import type { NotificationConfigData } from '$lib/types/operation-config';
	import { getSubscribers } from '$lib/api/settings';
	import { createQuery } from '@tanstack/svelte-query';
	import ColumnDropdown from '$lib/components/common/ColumnDropdown.svelte';
	import MultiSelectColumnDropdown from '$lib/components/common/MultiSelectColumnDropdown.svelte';
	import Callout from '$lib/components/ui/Callout.svelte';
	import ToggleButton from '$lib/components/ui/ToggleButton.svelte';
	import { Search } from 'lucide-svelte';
	import { css, input, label, stepConfig } from '$lib/styles/panda';

	interface Props {
		config?: NotificationConfigData;
		schema: Schema;
		configFlags?: { smtpEnabled: boolean; telegramEnabled: boolean };
	}

	const defaultConfig: NotificationConfigData = {
		method: 'email',
		recipient: '',
		subscriber_ids: [],
		bot_token: '',
		recipient_source: 'manual',
		recipient_column: '',
		input_columns: [],
		output_column: 'notification_status',
		message_template: '{{message}}',
		subject_template: 'Notification',
		batch_size: 10
	};

	let {
		config = $bindable(defaultConfig),
		schema,
		configFlags = { smtpEnabled: true, telegramEnabled: true }
	}: Props = $props();

	const canEmail = $derived(configFlags.smtpEnabled);
	const canTelegram = $derived(configFlags.telegramEnabled);
	const method = $derived(config?.method ?? 'email');
	const inputColumns = $derived(Array.isArray(config?.input_columns) ? config.input_columns : []);
	const subscriberIds = $derived(
		Array.isArray(config?.subscriber_ids) ? config.subscriber_ids : []
	);
	const recipientSource = $derived(config?.recipient_source === 'column' ? 'column' : 'manual');
	const recipientColumn = $derived(
		typeof config?.recipient_column === 'string' ? config.recipient_column : ''
	);
	const isReady = $derived(
		(method === 'email' && canEmail) || (method === 'telegram' && canTelegram)
	);
	let search = $state('');

	const subscribersQuery = createQuery(() => ({
		queryKey: ['telegram-subscribers'],
		queryFn: async () => {
			const result = await getSubscribers();
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		staleTime: 30_000,
		enabled: canTelegram
	}));

	const activeSubscribers = $derived(
		(subscribersQuery.data ?? []).filter((s: Subscriber) => s.is_active)
	);

	const filtered = $derived.by(() => {
		const q = search.toLowerCase().trim();
		if (!q) return activeSubscribers;
		return activeSubscribers.filter(
			(s: Subscriber) => s.title.toLowerCase().includes(q) || s.chat_id.toLowerCase().includes(q)
		);
	});

	function handleColumnsChange(columns: string[]) {
		config.input_columns = columns;
	}

	function handleMethodChange(next: 'email' | 'telegram') {
		const prev = config.method;
		config.method = next;
		if (next === 'email') {
			config.recipient_source = 'manual';
			config.recipient_column = '';
			config.subscriber_ids = [];
			if (prev === 'telegram') {
				config.recipient = '';
			}
			return;
		}
		if (config.recipient_source !== 'column') {
			config.recipient_source = 'manual';
		}
	}

	function handleRecipientColumnChange(column: string) {
		config.recipient_column = column;
	}

	function handleRecipientSourceChange(source: 'manual' | 'column') {
		config.recipient_source = source;
		if (source === 'column') {
			config.recipient = '';
			config.subscriber_ids = [];
			return;
		}
		config.recipient_column = '';
	}

	function toggleSubscriber(chatId: string) {
		const next = [...subscriberIds];
		const idx = next.indexOf(chatId);
		if (idx >= 0) {
			next.splice(idx, 1);
		} else {
			next.push(chatId);
		}
		config.subscriber_ids = next;
		if (config.method === 'telegram') {
			config.recipient = next.join(',');
		}
	}

	function isSelected(chatId: string): boolean {
		return subscriberIds.includes(chatId);
	}

	const placeholderHint = $derived.by(() => {
		if (inputColumns.length === 0) return 'Select column(s), then use {{column_name}} in template';
		if (inputColumns.length === 1)
			return `Use {{${inputColumns[0]}}} to reference the column value`;
		return `Use {{${inputColumns.join('}}, {{')}}} in template`;
	});
</script>

<div class={stepConfig()} role="region" aria-label="Notification configuration">
	{#if !isReady}
		<Callout tone="warn">Configure SMTP or Telegram in global settings first.</Callout>
	{/if}

	<div class={css({ marginBottom: '5' })}>
		<label class={label()} for="notify-method">Method</label>
		<select
			id="notify-method"
			class={input()}
			value={config.method}
			onchange={(e) => handleMethodChange(e.currentTarget.value as 'email' | 'telegram')}
		>
			<option value="email" disabled={!canEmail}>Email (SMTP)</option>
			<option value="telegram" disabled={!canTelegram}>Telegram</option>
		</select>
	</div>

	<div class={css({ marginBottom: '5' })}>
		{#if method === 'email'}
			<label class={label()} for="notify-recipient">Email Address</label>
			<input
				id="notify-recipient"
				type="text"
				class={input()}
				bind:value={config.recipient}
				placeholder="user@example.com"
			/>
		{:else}
			<div class={css({ display: 'flex', flexDirection: 'column', gap: '3' })}>
				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'space-between',
						gap: '3'
					})}
				>
					<span class={css({ fontSize: '2xs', textTransform: 'uppercase', color: 'fg.muted' })}>
						Recipient Source
					</span>
					<div class={css({ display: 'flex' })} role="radiogroup" aria-label="Recipient source">
						<ToggleButton
							active={recipientSource === 'manual'}
							radius="left"
							onclick={() => handleRecipientSourceChange('manual')}
							ariaPressed={recipientSource === 'manual'}
						>
							Subscribers
						</ToggleButton>
						<ToggleButton
							active={recipientSource === 'column'}
							radius="right"
							onclick={() => handleRecipientSourceChange('column')}
							ariaPressed={recipientSource === 'column'}
						>
							Column
						</ToggleButton>
					</div>
				</div>
				{#if recipientSource === 'column'}
					<span class={css({ fontSize: '2xs', textTransform: 'uppercase', color: 'fg.muted' })}>
						Recipient Column
					</span>
					<ColumnDropdown
						{schema}
						value={recipientColumn}
						onChange={handleRecipientColumnChange}
						placeholder="Select recipient column..."
						filter={(col) =>
							col.dtype.toLowerCase().includes('string') ||
							col.dtype.toLowerCase().includes('list')}
					/>
					<span class={css({ fontSize: '2xs', color: 'fg.muted' })}>
						Use string or list[string] columns. Comma-separated strings are supported.
					</span>
				{:else}
					<span class={css({ fontSize: '2xs', textTransform: 'uppercase', color: 'fg.muted' })}>
						Recipients
					</span>
					<div class={css({ position: 'relative' })}>
						<Search
							size={12}
							class={css({
								pointerEvents: 'none',
								position: 'absolute',
								left: '2',
								top: '50%',
								transform: 'translateY(-50%)',
								color: 'fg.muted'
							})}
						/>
						<input
							id="notif-search"
							aria-label="Search subscribers"
							class={[
								input({ variant: 'searchCompact' }),
								css({ paddingLeft: '7', paddingRight: '2' })
							]}
							placeholder="Search subscribers..."
							value={search}
							oninput={(e) => (search = e.currentTarget.value)}
						/>
					</div>
					<div
						class={css({
							maxHeight: 'colMd',
							overflowY: 'auto',
							borderWidth: '1',
							backgroundColor: 'bg.secondary'
						})}
					>
						{#if subscribersQuery.isPending}
							<div
								class={css({
									padding: '2',
									textAlign: 'center',
									fontSize: '2xs',
									color: 'fg.muted'
								})}
							>
								Loading...
							</div>
						{:else if subscribersQuery.isError}
							<div
								class={css({
									padding: '2',
									textAlign: 'center',
									fontSize: '2xs',
									color: 'fg.error'
								})}
							>
								Failed to load subscribers
							</div>
						{:else if activeSubscribers.length === 0}
							<div
								class={css({
									padding: '2',
									textAlign: 'center',
									fontSize: '2xs',
									color: 'fg.muted'
								})}
							>
								No subscribers. Users can subscribe via /subscribe in Telegram.
							</div>
						{:else if filtered.length === 0}
							<div
								class={css({
									padding: '2',
									textAlign: 'center',
									fontSize: '2xs',
									color: 'fg.muted'
								})}
							>
								No matches
							</div>
						{:else}
							{#each filtered as sub (sub.id)}
								<label
									class={css({
										display: 'flex',
										cursor: 'pointer',
										alignItems: 'center',
										gap: '3',
										fontSize: 'sm',
										fontWeight: 'normal',
										color: 'fg.secondary',
										textTransform: 'none',
										letterSpacing: 'normal',
										marginBottom: '0',
										borderBottomWidth: '1',
										paddingX: '2',
										paddingY: '1.5',
										_hover: { backgroundColor: 'bg.tertiary' },
										_last: { borderBottomWidth: '0' }
									})}
								>
									<input
										id={`sub-${sub.id}`}
										type="checkbox"
										checked={isSelected(sub.chat_id)}
										onchange={() => toggleSubscriber(sub.chat_id)}
									/>
									<span
										class={css({
											overflow: 'hidden',
											textOverflow: 'ellipsis',
											whiteSpace: 'nowrap',
											fontSize: 'xs'
										})}
									>
										{sub.title}
									</span>
									<span
										class={css({
											marginLeft: 'auto',
											flexShrink: '0',
											fontSize: '2xs',
											color: 'fg.muted'
										})}
									>
										{sub.chat_id}
									</span>
								</label>
							{/each}
						{/if}
					</div>
				{/if}
			</div>
		{/if}
	</div>

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
		<label class={label()} for="notify-output">Output Column</label>
		<input
			id="notify-output"
			type="text"
			class={input()}
			bind:value={config.output_column}
			placeholder="notification_status"
		/>
	</div>

	{#if config.method === 'email'}
		<div class={css({ marginBottom: '4' })}>
			<label class={label()} for="notify-subject">Subject Template</label>
			<input id="notify-subject" type="text" class={input()} bind:value={config.subject_template} />
		</div>
	{/if}

	<div class={css({ marginBottom: '0' })}>
		<label class={label()} for="notify-message">Message Template</label>
		<textarea id="notify-message" class={input()} rows="4" bind:value={config.message_template}
		></textarea>
		<span class={css({ marginTop: '1', display: 'block', fontSize: 'xs', color: 'fg.muted' })}>
			{placeholderHint}
		</span>
	</div>
</div>
