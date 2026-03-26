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
	import PanelHeader from '$lib/components/ui/PanelHeader.svelte';
	import SectionHeader from '$lib/components/ui/SectionHeader.svelte';
	import { css, input, cx, label, row, rowBetween, divider } from '$lib/styles/panda';

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
			<Loader2 size={14} class={css({ animation: 'spin 1s linear infinite' })} />
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
									backgroundColor: 'success.bg',
									color: 'success.fg'
								}
							: { borderColor: 'border.error', backgroundColor: 'error.bg', color: 'error.fg' })
					})}
				>
					{#if feedback.type === 'success'}
						<CheckCircle size={12} />
					{:else}
						<XCircle size={12} />
					{/if}
					{feedback.message}
				</div>
			{/if}

			<SectionHeader>
				<Mail size={12} class={css({ marginRight: '1', display: 'inline' })} />
				SMTP
			</SectionHeader>

			<div
				class={css({ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '2' })}
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
				class={css({ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '2' })}
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
						placeholder="••••••••"
					/>
				</label>
			</div>

			<div class={css({ display: 'flex', alignItems: 'flex-end', gap: '2' })}>
				<label class={cx(label({ variant: 'wrapper' }), css({ flex: '1' }))}>
					<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>Test recipient</span>
					<input
						type="email"
						class={input()}
						id="smtp-test-to"
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
					type="button"
				>
					{#if testingSmtp}
						<Loader2 size={12} class={css({ animation: 'spin 1s linear infinite' })} />
					{:else}
						<Send size={12} />
					{/if}
					Test
				</button>
			</div>

			<div
				class={css({
					borderBottomWidth: '1'
				})}
			></div>

			<div class={cx(row, css({ gap: '2' }))}>
				<SectionHeader>
					<MessageCircle size={12} class={css({ marginRight: '1', display: 'inline' })} />
					Telegram
				</SectionHeader>
				{#if statusQuery.data}
					<span
						class={css({
							display: 'inline-block',
							height: 'dot',
							width: 'dot',
							flexShrink: '0',
							backgroundColor: botRunning ? 'success.fg' : 'error.fg'
						})}
						title={botRunning ? 'Bot running' : 'Bot stopped'}
					></span>
				{/if}
			</div>

			<label class={label({ variant: 'wrapper' })}>
				<span class={css({ fontSize: 'xs', color: 'fg.tertiary' })}>Bot token</span>
				<input
					type="password"
					class={input()}
					id="telegram-bot-token"
					bind:value={telegram_bot_token}
					placeholder="123456:ABC-DEF..."
				/>
			</label>

			<div class={rowBetween}>
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
					<span class={cx(row, css({ gap: '1.5' }))}>
						<span
							class={css({
								display: 'inline-block',
								height: 'barTall',
								width: 'barTall',
								flexShrink: '0',
								backgroundColor: botRunning ? 'success.fg' : 'error.fg'
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
							<div class={cx(row, css({ gap: '2' }))}>
								<span
									class={css({
										display: 'inline-block',
										height: 'barTall',
										width: 'barTall',
										flexShrink: '0',
										backgroundColor: sub.is_active ? 'success.fg' : 'bg.tertiary'
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

			<div
				class={css({
					borderBottomWidth: '1'
				})}
			></div>

			<SectionHeader>
				<Database size={12} class={css({ marginRight: '1', display: 'inline' })} />
				Debug
			</SectionHeader>

			<div class={rowBetween}>
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

		<div
			class={cx(
				divider,
				css({
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'space-between',
					padding: '4'
				})
			)}
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
					<Loader2 size={12} class={css({ animation: 'spin 1s linear infinite' })} />
				{:else}
					<Save size={12} />
				{/if}
				Save
			</button>
		</div>
	{/if}
{/snippet}
