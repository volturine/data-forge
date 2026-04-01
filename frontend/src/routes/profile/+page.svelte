<script lang="ts">
	import { css, cx, button, input, label, spinner, row } from '$lib/styles/panda';
	import { authStore } from '$lib/stores/auth.svelte';
	import { configStore } from '$lib/stores/config.svelte';
	import { updateProfile, changePassword, unlinkProvider, getMe } from '$lib/api/auth';
	import { Github } from 'lucide-svelte';

	const editable = $derived(configStore.authRequired);

	let name = $state(authStore.user?.display_name ?? '');
	let saving = $state(false);
	let message = $state<{ text: string; kind: 'success' | 'error' } | null>(null);

	let current = $state('');
	let fresh = $state('');
	let confirm = $state('');
	let changing = $state(false);
	let pwMessage = $state<{ text: string; kind: 'success' | 'error' } | null>(null);

	let unlinking = $state<string | null>(null);
	let linkMessage = $state<{ text: string; kind: 'success' | 'error' } | null>(null);

	const providers = $derived(authStore.user?.providers ?? []);

	function connected(p: string): boolean {
		return providers.includes(p);
	}

	async function saveProfile(e: SubmitEvent) {
		e.preventDefault();
		saving = true;
		message = null;
		const result = await updateProfile({ display_name: name });
		result.match(
			(user) => {
				authStore.user = user;
				message = { text: 'Profile updated', kind: 'success' };
			},
			(err) => {
				message = { text: err.message, kind: 'error' };
			}
		);
		saving = false;
	}

	async function savePassword(e: SubmitEvent) {
		e.preventDefault();
		pwMessage = null;

		if (fresh.length < 8) {
			pwMessage = { text: 'Password must be at least 8 characters', kind: 'error' };
			return;
		}
		if (fresh !== confirm) {
			pwMessage = { text: 'Passwords do not match', kind: 'error' };
			return;
		}

		changing = true;
		const result = await changePassword({ current_password: current, new_password: fresh });
		result.match(
			() => {
				pwMessage = { text: 'Password changed', kind: 'success' };
				current = '';
				fresh = '';
				confirm = '';
			},
			(err) => {
				pwMessage = { text: err.message, kind: 'error' };
			}
		);
		changing = false;
	}

	function oauth(provider: string) {
		window.location.href = `/api/v1/auth/${provider}`;
	}

	async function disconnect(provider: string) {
		unlinking = provider;
		linkMessage = null;
		const result = await unlinkProvider(provider);
		result.match(
			() => {
				linkMessage = { text: `${provider} disconnected`, kind: 'success' };
			},
			(err) => {
				linkMessage = { text: err.message, kind: 'error' };
			}
		);
		const refresh = await getMe();
		refresh.match(
			(user) => {
				authStore.user = user;
			},
			() => {}
		);
		unlinking = null;
	}

	const card = css({
		backgroundColor: 'bg.panel',
		borderWidth: '1',
		padding: '6',
		display: 'flex',
		flexDirection: 'column',
		gap: '5'
	});

	const heading = css({
		fontSize: 'md',
		fontWeight: 'semibold',
		color: 'fg.primary',
		paddingBottom: '3',
		borderBottomWidth: '1',
		borderColor: 'border.primary'
	});

	const alert = (kind: 'success' | 'error') =>
		css({
			backgroundColor: kind === 'success' ? 'bg.success' : 'bg.error',
			borderWidth: '1',
			borderColor: kind === 'success' ? 'border.success' : 'border.error',
			color: kind === 'success' ? 'fg.success' : 'fg.error',
			paddingX: '3',
			paddingY: '2',
			fontSize: 'sm'
		});
</script>

<div
	class={css({
		maxWidth: '640px',
		marginX: 'auto',
		width: '100%',
		paddingX: '6',
		paddingY: '8',
		display: 'flex',
		flexDirection: 'column',
		gap: '6'
	})}
>
	<div>
		<h1 class={css({ fontSize: 'xl', fontWeight: 'semibold', color: 'fg.primary' })}>Profile</h1>
		<p class={css({ fontSize: 'sm', color: 'fg.muted', marginTop: '1' })}>
			Manage your account settings
		</p>
	</div>

	<div class={card}>
		<h2 class={heading}>Profile</h2>

		{#if message}
			<div class={alert(message.kind)}>{message.text}</div>
		{/if}

		<form
			onsubmit={saveProfile}
			class={css({ display: 'flex', flexDirection: 'column', gap: '4' })}
		>
			<div>
				<label for="email" class={label({ variant: 'field' })}>Email</label>
				<input
					id="email"
					type="email"
					class={cx(input(), css({ opacity: '0.6', cursor: 'not-allowed' }))}
					value={authStore.user?.email ?? ''}
					disabled
				/>
			</div>

			<div>
				<label for="name" class={label({ variant: 'field' })}>Display name</label>
				<input
					id="name"
					type="text"
					class={input()}
					placeholder="Your name"
					bind:value={name}
					required
					disabled={!editable}
				/>
			</div>

			{#if editable}
				<div class={css({ display: 'flex', justifyContent: 'flex-end' })}>
					<button type="submit" class={button({ variant: 'primary' })} disabled={saving}>
						{#if saving}
							<div class={spinner({ size: 'sm' })}></div>
						{/if}
						Save
					</button>
				</div>
			{/if}
		</form>
	</div>

	{#if editable}
		<div class={card}>
			<h2 class={heading}>Password</h2>

			{#if pwMessage}
				<div class={alert(pwMessage.kind)}>{pwMessage.text}</div>
			{/if}

			<form
				onsubmit={savePassword}
				class={css({ display: 'flex', flexDirection: 'column', gap: '4' })}
			>
				<div>
					<label for="current" class={label({ variant: 'field' })}>Current password</label>
					<input
						id="current"
						type="password"
						class={input()}
						placeholder="Enter current password"
						bind:value={current}
						required
						autocomplete="current-password"
					/>
				</div>

				<div>
					<label for="fresh" class={label({ variant: 'field' })}>New password</label>
					<input
						id="fresh"
						type="password"
						class={input()}
						placeholder="At least 8 characters"
						bind:value={fresh}
						required
						minlength={8}
						autocomplete="new-password"
					/>
				</div>

				<div>
					<label for="confirm" class={label({ variant: 'field' })}>Confirm password</label>
					<input
						id="confirm"
						type="password"
						class={input()}
						placeholder="Repeat new password"
						bind:value={confirm}
						required
						minlength={8}
						autocomplete="new-password"
					/>
				</div>

				<div class={css({ display: 'flex', justifyContent: 'flex-end' })}>
					<button type="submit" class={button({ variant: 'primary' })} disabled={changing}>
						{#if changing}
							<div class={spinner({ size: 'sm' })}></div>
						{/if}
						Change password
					</button>
				</div>
			</form>
		</div>

		<div class={card}>
			<h2 class={heading}>Connected accounts</h2>

			{#if linkMessage}
				<div class={alert(linkMessage.kind)}>{linkMessage.text}</div>
			{/if}

			<div class={css({ display: 'flex', flexDirection: 'column', gap: '3' })}>
				<div class={cx(row, css({ justifyContent: 'space-between', paddingY: '2' }))}>
					<div class={cx(row, css({ gap: '3' }))}>
						<span class={css({ color: 'fg.primary', fontSize: 'sm' })}>Google</span>
						{#if connected('google')}
							<span
								class={css({
									fontSize: 'xs',
									color: 'fg.success',
									backgroundColor: 'bg.success',
									paddingX: '2',
									paddingY: '0.5',
									borderRadius: 'sm'
								})}
							>
								Connected
							</span>
						{/if}
					</div>
					{#if connected('google')}
						<button
							type="button"
							class={button({ variant: 'ghost', size: 'sm' })}
							disabled={unlinking === 'google'}
							onclick={() => disconnect('google')}
						>
							{#if unlinking === 'google'}
								<div class={spinner({ size: 'sm' })}></div>
							{/if}
							Disconnect
						</button>
					{:else}
						<button type="button" class={button({ size: 'sm' })} onclick={() => oauth('google')}>
							Connect
						</button>
					{/if}
				</div>

				<div class={css({ borderTopWidth: '1', borderColor: 'border.primary' })}></div>

				<div class={cx(row, css({ justifyContent: 'space-between', paddingY: '2' }))}>
					<div class={cx(row, css({ gap: '3' }))}>
						<Github size={16} />
						<span class={css({ color: 'fg.primary', fontSize: 'sm' })}>GitHub</span>
						{#if connected('github')}
							<span
								class={css({
									fontSize: 'xs',
									color: 'fg.success',
									backgroundColor: 'bg.success',
									paddingX: '2',
									paddingY: '0.5',
									borderRadius: 'sm'
								})}
							>
								Connected
							</span>
						{/if}
					</div>
					{#if connected('github')}
						<button
							type="button"
							class={button({ variant: 'ghost', size: 'sm' })}
							disabled={unlinking === 'github'}
							onclick={() => disconnect('github')}
						>
							{#if unlinking === 'github'}
								<div class={spinner({ size: 'sm' })}></div>
							{/if}
							Disconnect
						</button>
					{:else}
						<button type="button" class={button({ size: 'sm' })} onclick={() => oauth('github')}>
							<Github size={14} />
							Connect
						</button>
					{/if}
				</div>
			</div>
		</div>

		<div class={card}>
			<h2 class={cx(heading, css({ color: 'fg.error', borderColor: 'border.error' }))}>
				Danger zone
			</h2>

			<div class={cx(row, css({ justifyContent: 'space-between' }))}>
				<div>
					<p class={css({ fontSize: 'sm', color: 'fg.primary' })}>Delete account</p>
					<p class={css({ fontSize: 'xs', color: 'fg.muted' })}>
						Permanently remove your account and all data
					</p>
				</div>
				<button type="button" class={button({ variant: 'danger', size: 'sm' })} disabled>
					Coming soon
				</button>
			</div>
		</div>
	{/if}
</div>
