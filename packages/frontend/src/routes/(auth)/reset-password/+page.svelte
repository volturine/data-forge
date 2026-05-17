<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { css, button, input, label, spinner } from '$lib/styles/panda';
	import { resetPassword } from '$lib/api/auth';

	let password = $state('');
	let confirm = $state('');
	let loading = $state(false);
	let success = $state(false);
	let error = $state<string | null>(null);
	let validation = $state<string | null>(null);

	const token = $derived(page.url.searchParams.get('token'));
	const valid = $derived(password.length >= 8 && password === confirm);
	const displayed = $derived(validation ?? error);

	async function submit(e: SubmitEvent) {
		e.preventDefault();
		validation = null;

		if (password.length < 8) {
			validation = 'Password must be at least 8 characters';
			return;
		}
		if (password !== confirm) {
			validation = 'Passwords do not match';
			return;
		}
		if (!token) {
			validation = 'Missing reset token';
			return;
		}

		loading = true;
		error = null;
		const result = await resetPassword(token, password);
		result.match(
			() => {
				success = true;
			},
			(err) => {
				error = err.message;
			}
		);
		loading = false;
	}
</script>

<div
	class={css({
		backgroundColor: 'bg.panel',
		borderWidth: '1',
		padding: '8',
		display: 'flex',
		flexDirection: 'column',
		gap: '6'
	})}
>
	<div>
		<h1 class={css({ fontSize: 'lg', fontWeight: 'semibold', color: 'fg.primary' })}>
			Reset password
		</h1>
		<p class={css({ fontSize: 'sm', color: 'fg.muted', marginTop: '1' })}>
			{#if !token}
				Invalid reset link. Please request a new one.
			{:else if success}
				Your password has been reset
			{:else}
				Choose a new password for your account
			{/if}
		</p>
	</div>

	{#if displayed}
		<div
			class={css({
				backgroundColor: 'bg.error',
				borderWidth: '1',
				borderColor: 'border.error',
				color: 'fg.error',
				paddingX: '3',
				paddingY: '2',
				fontSize: 'sm'
			})}
		>
			{displayed}
		</div>
	{/if}

	{#if success}
		<div
			class={css({
				backgroundColor: 'bg.success',
				borderWidth: '1',
				borderColor: 'border.success',
				color: 'fg.success',
				paddingX: '3',
				paddingY: '2',
				fontSize: 'sm'
			})}
		>
			Your password has been reset successfully. You can now sign in with your new password.
		</div>

		<a href={resolve('/login')} class={button({ variant: 'primary' })}> Continue to sign in </a>
	{:else if token}
		<form onsubmit={submit} class={css({ display: 'flex', flexDirection: 'column', gap: '4' })}>
			<div>
				<label for="password" class={label({ variant: 'field' })}>New password</label>
				<input
					id="password"
					type="password"
					class={input()}
					placeholder="At least 8 characters"
					bind:value={password}
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
					placeholder="Repeat your password"
					bind:value={confirm}
					required
					minlength={8}
					autocomplete="new-password"
				/>
			</div>

			<button type="submit" class={button({ variant: 'primary' })} disabled={loading || !valid}>
				{#if loading}
					<div class={spinner({ size: 'sm' })}></div>
				{/if}
				Reset password
			</button>
		</form>
	{/if}

	{#if !token}
		<a href={resolve('/forgot-password')} class={button({ variant: 'primary' })}>
			Request new reset link
		</a>
	{/if}

	<p class={css({ fontSize: 'sm', color: 'fg.muted', textAlign: 'center' })}>
		<a
			href={resolve('/login')}
			class={css({
				color: 'accent.primary',
				textDecoration: 'underline',
				textUnderlineOffset: '2px'
			})}
		>
			Back to sign in
		</a>
	</p>
</div>
