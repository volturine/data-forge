<script lang="ts">
	import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
	import {
		X,
		Mail,
		MessageCircle,
		Database,
		CheckCircle,
		XCircle,
		Send,
		Save,
		Loader2,
		Trash2
	} from 'lucide-svelte';
	import {
		getSettings,
		updateSettings,
		testSmtp,
		getBotStatus,
		getSubscribers,
		deleteSubscriber
	} from '$lib/api/settings';
	import { configStore } from '$lib/stores/config.svelte';
	import BaseModal from '$lib/components/ui/BaseModal.svelte';

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
	let idb = $state(false);

	// UI state
	let loading = $state(false);
	let saving = $state(false);
	let testingSmtp = $state(false);
	let smtpTestTo = $state('');
	let feedback = $state<{ type: 'success' | 'error'; message: string } | null>(null);

	// Network: $derived can't fetch settings on open.
	$effect(() => {
		if (!open) return;
		loading = true;
		feedback = null;
		let aborted = false;
		getSettings().match(
			(s) => {
				if (aborted) return;
				smtp_host = s.smtp_host;
				smtp_port = s.smtp_port;
				smtp_user = s.smtp_user;
				smtp_password = s.smtp_password;
				telegram_bot_token = s.telegram_bot_token;
				telegram_bot_enabled = s.telegram_bot_enabled;
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

	function handleKeydown(e: KeyboardEvent) {
		if (!open) return;
		if (e.key === 'Escape') {
			e.preventDefault();
			open = false;
		}
	}

	async function save() {
		saving = true;
		feedback = null;
		const result = await updateSettings({
			smtp_host,
			smtp_port,
			smtp_user,
			smtp_password,
			telegram_bot_token,
			telegram_bot_enabled,
			public_idb_debug: idb
		});
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

</script>

<svelte:window onkeydown={handleKeydown} />

<BaseModal
	open={open}
	onClose={() => (open = false)}
	closeOnEscape={true}
	closeOnBackdrop={true}
	panelClass="w-full max-w-120 max-h-[90vh] overflow-y-auto border animate-slide-up bg-dialog border-tertiary focus:outline-none"
	ariaLabelledby="settings-title"
	content={content}
/>

{#snippet content()}
	<div class="flex items-center justify-between border-b p-4 border-tertiary">
		<h2 id="settings-title" class="m-0 text-sm font-semibold text-fg-primary">Settings</h2>
		<button
			class="flex cursor-pointer items-center justify-center border-none bg-transparent p-1 text-fg-muted hover:bg-hover hover:text-fg-primary"
			onclick={() => (open = false)}
			aria-label="Close settings"
			type="button"
		>
			<X size={16} />
		</button>
	</div>

	{#if loading}
		<div class="flex items-center justify-center gap-2 p-8 text-xs text-fg-muted">
			<Loader2 size={14} class="animate-spin" />
			Loading settings...
		</div>
	{:else}
		<div class="flex flex-col gap-4 p-4">
			{#if feedback}
				<div
					class="flex items-center gap-2 border p-2 text-xs"
					class:border-success={feedback.type === 'success'}
					class:bg-success={feedback.type === 'success'}
					class:text-success={feedback.type === 'success'}
					class:border-error={feedback.type === 'error'}
					class:bg-error={feedback.type === 'error'}
					class:text-error={feedback.type === 'error'}
				>
					{#if feedback.type === 'success'}
						<CheckCircle size={12} />
					{:else}
						<XCircle size={12} />
					{/if}
					{feedback.message}
				</div>
			{/if}

			<span class="text-xs font-semibold uppercase tracking-wider text-fg-tertiary">
				<Mail size={12} class="mr-1 inline" />
				SMTP
			</span>

			<div class="grid grid-cols-2 gap-2">
				<label class="flex flex-col gap-1">
					<span class="text-xs text-fg-tertiary">Host</span>
					<input
						type="text"
						class="w-full border bg-transparent px-2 py-1.5 text-xs text-fg-primary border-tertiary focus:border-accent-primary focus:outline-none"
						bind:value={smtp_host}
						placeholder="smtp.example.com"
					/>
				</label>
				<label class="flex flex-col gap-1">
					<span class="text-xs text-fg-tertiary">Port</span>
					<input
						type="number"
						class="w-full border bg-transparent px-2 py-1.5 text-xs text-fg-primary border-tertiary focus:border-accent-primary focus:outline-none"
						bind:value={smtp_port}
					/>
				</label>
			</div>

			<div class="grid grid-cols-2 gap-2">
				<label class="flex flex-col gap-1">
					<span class="text-xs text-fg-tertiary">User</span>
					<input
						type="text"
						class="w-full border bg-transparent px-2 py-1.5 text-xs text-fg-primary border-tertiary focus:border-accent-primary focus:outline-none"
						bind:value={smtp_user}
						placeholder="user@example.com"
					/>
				</label>
				<label class="flex flex-col gap-1">
					<span class="text-xs text-fg-tertiary">Password</span>
					<input
						type="password"
						class="w-full border bg-transparent px-2 py-1.5 text-xs text-fg-primary border-tertiary focus:border-accent-primary focus:outline-none"
						bind:value={smtp_password}
						placeholder="••••••••"
					/>
				</label>
			</div>

			<div class="flex items-end gap-2">
				<label class="flex flex-1 flex-col gap-1">
					<span class="text-xs text-fg-tertiary">Test recipient</span>
					<input
						type="email"
						class="w-full border bg-transparent px-2 py-1.5 text-xs text-fg-primary border-tertiary focus:border-accent-primary focus:outline-none"
						bind:value={smtpTestTo}
						placeholder="test@example.com"
					/>
				</label>
				<button
					class="flex shrink-0 cursor-pointer items-center gap-1 border px-3 py-1.5 text-xs font-medium border-tertiary bg-tertiary text-fg-secondary hover:bg-hover hover:text-fg-primary disabled:cursor-not-allowed disabled:opacity-50"
					onclick={handleTestSmtp}
					disabled={testingSmtp || !smtpTestTo}
					type="button"
				>
					{#if testingSmtp}
						<Loader2 size={12} class="animate-spin" />
					{:else}
						<Send size={12} />
					{/if}
					Test
				</button>
			</div>

			<div class="border-b border-tertiary"></div>

			<div class="flex items-center gap-2">
				<span class="text-xs font-semibold uppercase tracking-wider text-fg-tertiary">
					<MessageCircle size={12} class="mr-1 inline" />
					Telegram
				</span>
				{#if statusQuery.data}
					<span
						class="inline-block h-2 w-2 shrink-0"
						class:bg-success={botRunning}
						class:bg-error={!botRunning}
						title={botRunning ? 'Bot running' : 'Bot stopped'}
					></span>
				{/if}
			</div>

			<label class="flex flex-col gap-1">
				<span class="text-xs text-fg-tertiary">Bot token</span>
				<input
					type="password"
					class="w-full border bg-transparent px-2 py-1.5 text-xs text-fg-primary border-tertiary focus:border-accent-primary focus:outline-none"
					bind:value={telegram_bot_token}
					placeholder="123456:ABC-DEF..."
				/>
			</label>

			<div class="flex items-center justify-between">
				<div class="flex flex-col gap-0.5">
					<span class="text-sm font-medium text-fg-primary">Enable Bot</span>
					<span class="text-xs text-fg-tertiary">Start the Telegram bot listener on save</span>
				</div>
				<button
					class="relative h-5 w-9 cursor-pointer border-none transition-colors"
					class:bg-accent-primary={telegram_bot_enabled}
					class:bg-tertiary={!telegram_bot_enabled}
					onclick={() => (telegram_bot_enabled = !telegram_bot_enabled)}
					type="button"
					role="switch"
					aria-checked={telegram_bot_enabled}
					aria-label="Toggle Telegram bot"
				>
					<span
						class="absolute top-0.5 left-0.5 h-4 w-4 bg-fg-primary transition-transform"
						class:translate-x-4={telegram_bot_enabled}
					></span>
				</button>
			</div>

			{#if statusQuery.data}
				<div class="flex items-center justify-between border px-3 py-2 text-xs border-tertiary bg-tertiary">
					<span class="flex items-center gap-1.5">
						<span
							class="inline-block h-1.5 w-1.5 shrink-0"
							class:bg-success={botRunning}
							class:bg-error={!botRunning}
						></span>
						<span class="text-fg-secondary">
							{botRunning ? 'Bot running' : 'Bot stopped'}
						</span>
					</span>
					<span class="text-fg-tertiary">
						{statusQuery.data.subscriber_count}
						{statusQuery.data.subscriber_count === 1 ? 'subscriber' : 'subscribers'}
					</span>
				</div>
			{/if}

			{#if subscribers.length > 0}
				<div class="flex flex-col border border-tertiary">
					{#each subscribers as sub (sub.id)}
						<div
							class="flex items-center justify-between border-b px-3 py-2 text-xs last:border-b-0 border-tertiary"
						>
							<div class="flex items-center gap-2">
								<span
									class="inline-block h-1.5 w-1.5 shrink-0"
									class:bg-success={sub.is_active}
									class:bg-tertiary={!sub.is_active}
									title={sub.is_active ? 'Active' : 'Inactive'}
								></span>
								<span class="font-medium text-fg-primary">{sub.title}</span>
								<span class="text-fg-tertiary">{sub.chat_id}</span>
							</div>
							<button
								class="flex cursor-pointer items-center justify-center border-none bg-transparent p-1 text-fg-tertiary transition-colors hover:text-error"
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
				<p class="m-0 text-xs text-fg-tertiary">
					Subscribers appear here after users send /subscribe to your bot.
				</p>
			{/if}

			<div class="border-b border-tertiary"></div>

			<span class="text-xs font-semibold uppercase tracking-wider text-fg-tertiary">
				<Database size={12} class="mr-1 inline" />
				Debug
			</span>

			<div class="flex items-center justify-between">
				<div class="flex flex-col gap-0.5">
					<span class="text-sm font-medium text-fg-primary">IndexedDB Inspector</span>
					<span class="text-xs text-fg-tertiary">Show cache debug button in header</span>
				</div>
				<button
					class="relative h-5 w-9 cursor-pointer border-none transition-colors"
					class:bg-accent-primary={idb}
					class:bg-tertiary={!idb}
					onclick={() => (idb = !idb)}
					type="button"
					role="switch"
					aria-checked={idb}
					aria-label="Toggle IndexedDB inspector"
				>
					<span
						class="absolute top-0.5 left-0.5 h-4 w-4 bg-fg-primary transition-transform"
						class:translate-x-4={idb}
					></span>
				</button>
			</div>
		</div>

		<div class="flex items-center justify-between border-t p-4 border-tertiary">
			<p class="m-0 text-xs text-fg-tertiary">Settings are stored in the database.</p>
			<button
				class="flex cursor-pointer items-center gap-1.5 border-none px-4 py-2 text-xs font-medium bg-accent text-bg-primary hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
				onclick={save}
				disabled={saving}
				type="button"
			>
				{#if saving}
					<Loader2 size={12} class="animate-spin" />
				{:else}
					<Save size={12} />
				{/if}
				Save
			</button>
		</div>
	{/if}
{/snippet}
