<script lang="ts">
	import { resolve } from '$app/paths';
	import { css, button, input, label, spinner } from '$lib/styles/panda';
	import { forgotPassword } from '$lib/api/auth';

	let email = $state('');
	let loading = $state(false);
	let sent = $state(false);
	let error = $state<string | null>(null);

	async function submit(e: SubmitEvent) {
		e.preventDefault();
		loading = true;
		error = null;
		const result = await forgotPassword(email);
		result.match(
			() => {
				sent = true;
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
			Forgot password
		</h1>
		<p class={css({ fontSize: 'sm', color: 'fg.muted', marginTop: '1' })}>
			Enter your email to receive a reset link
		</p>
	</div>

	{#if error}
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
			{error}
		</div>
	{/if}

	{#if sent}
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
			If an account exists with that email, a password reset link has been sent.
		</div>
	{:else}
		<form onsubmit={submit} class={css({ display: 'flex', flexDirection: 'column', gap: '4' })}>
			<div>
				<label for="email" class={label({ variant: 'field' })}>Email</label>
				<input
					id="email"
					type="email"
					class={input()}
					placeholder="you@example.com"
					bind:value={email}
					required
					autocomplete="email"
				/>
			</div>

			<button type="submit" class={button({ variant: 'primary' })} disabled={loading}>
				{#if loading}
					<div class={spinner({ size: 'sm' })}></div>
				{/if}
				Send reset link
			</button>
		</form>
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
