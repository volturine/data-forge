<script lang="ts">
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { css, button, spinner } from '$lib/styles/panda';
	import { verifyEmail, resendVerification } from '$lib/api/auth';

	let status = $state<'idle' | 'loading' | 'success' | 'error'>('idle');
	let message = $state('');
	let resending = $state(false);
	let resent = $state(false);

	const token = $derived(page.url.searchParams.get('token'));

	// Side effect: auto-verify when token is present in URL on mount
	$effect(() => {
		if (!token) return;
		status = 'loading';
		verifyEmail(token).then((result) => {
			result.match(
				(data) => {
					status = 'success';
					message = data.message;
				},
				(err) => {
					status = 'error';
					message = err.message;
				}
			);
		});
	});

	async function resend() {
		resending = true;
		const result = await resendVerification();
		result.match(
			() => {
				resent = true;
			},
			(err) => {
				message = err.message;
			}
		);
		resending = false;
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
			Email verification
		</h1>
		<p class={css({ fontSize: 'sm', color: 'fg.muted', marginTop: '1' })}>
			{#if !token}
				Check your email for a verification link
			{:else if status === 'loading'}
				Verifying your email...
			{:else if status === 'success'}
				Your email has been verified
			{:else}
				Verification failed
			{/if}
		</p>
	</div>

	{#if status === 'loading'}
		<div class={css({ display: 'flex', justifyContent: 'center', paddingY: '4' })}>
			<div class={spinner({ size: 'md' })}></div>
		</div>
	{/if}

	{#if status === 'success'}
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
			{message}
		</div>

		<a href={resolve('/login')} class={button({ variant: 'primary' })}> Continue to sign in </a>
	{/if}

	{#if status === 'error'}
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
			{message}
		</div>

		{#if resent}
			<p class={css({ fontSize: 'sm', color: 'fg.muted', textAlign: 'center' })}>
				A new verification email has been sent. Check your inbox.
			</p>
		{:else}
			<button type="button" class={button()} disabled={resending} onclick={resend}>
				{#if resending}
					<div class={spinner({ size: 'sm' })}></div>
				{/if}
				Resend verification email
			</button>
		{/if}
	{/if}

	{#if !token}
		<p class={css({ fontSize: 'sm', color: 'fg.muted', textAlign: 'center' })}>
			A verification link has been sent to your email address. Check your inbox and click the link
			to verify your account.
		</p>
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
