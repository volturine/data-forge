<script lang="ts">
	import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
	import {
		Mail,
		MessageCircle,
		ChevronDown,
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
		deleteSubscriber,
		isMasked,
		MASKED_PLACEHOLDER
	} from '$lib/api/settings';
	import type { AppSettings } from '$lib/api/settings';
	import { configStore } from '$lib/stores/config.svelte';
	import SectionHeader from '$lib/components/ui/SectionHeader.svelte';
	import { css, input, label } from '$lib/styles/panda';

	let loading = $state(true);
	let saving = $state(false);
	let testingSmtp = $state(false);
	let smtpTestTo = $state('');
	let feedback = $state<{ type: 'success' | 'error'; message: string } | null>(null);
	let smtpCollapsed = $state(false);
	let telegramCollapsed = $state(true);

	// SMTP fields
	let smtp_host = $state('');
	let smtp_port = $state(587);
	let smtp_user = $state('');
	let smtp_password = $state('');
	let smtp_password_dirty = $state(false);

	// Telegram fields
	let telegram_bot_token = $state('');
	let telegram_bot_enabled = $state(false);
	let telegram_bot_token_dirty = $state(false);

	const queryClient = useQueryClient();

	// Network: load settings on mount.
	$effect(() => {
		loading = true;
		feedback = null;
		smtp_password_dirty = false;
		telegram_bot_token_dirty = false;
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

	const statusQuery = createQuery(() => ({
		queryKey: ['telegram-status'],
		queryFn: async () => {
			const result = await getBotStatus();
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		staleTime: 10_000
	}));

	const subscribersQuery = createQuery(() => ({
		queryKey: ['telegram-subscribers'],
		queryFn: async () => {
			const result = await getSubscribers();
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		staleTime: 10_000
	}));

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
			telegram_bot_enabled
		};
		if (smtp_password_dirty) payload.smtp_password = smtp_password;
		if (telegram_bot_token_dirty) payload.telegram_bot_token = telegram_bot_token;
		const result = await updateSettings(payload);
		result.match(
			() => {
				feedback = { type: 'success', message: 'Notification settings saved' };
				configStore['fetched'] = false;
				configStore.fetch();
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
		Loading notification settings…
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
				gap: '5'
			})}
		>
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
				aria-controls="notifications-smtp"
				onclick={() => (smtpCollapsed = !smtpCollapsed)}
			>
				<span class={css({ display: 'inline-flex', alignItems: 'center', gap: '1.5' })}>
					<Mail size={14} />
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
				id="notifications-smtp"
				hidden={smtpCollapsed}
				aria-hidden={smtpCollapsed}
				class={css(
					{ display: 'flex', flexDirection: 'column', gap: '3' },
					smtpCollapsed && { display: 'none' }
				)}
			>
				<div
					class={css({
						display: 'grid',
						gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
						gap: '3'
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
						gap: '3'
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
							<Loader2 size={12} class={css({ animation: 'spin 1s linear infinite' })} />
						{:else}
							<Send size={12} />
						{/if}
						Test
					</button>
				</div>
			</div>
		</div>

		<div
			class={css({
				backgroundColor: 'bg.panel',
				borderWidth: '1',
				padding: '6',
				display: 'flex',
				flexDirection: 'column',
				gap: '5'
			})}
		>
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
				aria-controls="notifications-telegram"
				onclick={() => (telegramCollapsed = !telegramCollapsed)}
			>
				<span class={css({ display: 'inline-flex', alignItems: 'center', gap: '1.5' })}>
					<MessageCircle size={14} />
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
				id="notifications-telegram"
				hidden={telegramCollapsed}
				aria-hidden={telegramCollapsed}
				class={css(
					{ display: 'flex', flexDirection: 'column', gap: '3' },
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
					class={css({
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'space-between'
					})}
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
