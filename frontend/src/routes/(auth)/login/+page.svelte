<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { css, cx, button, input, label, spinner } from '$lib/styles/panda';
	import { authStore } from '$lib/stores/auth.svelte';
	import { GitBranch } from 'lucide-svelte';

	let email = $state('');
	let password = $state('');

	async function submit(e: SubmitEvent) {
		e.preventDefault();
		const success = await authStore.login(email, password);
		if (success) void goto(resolve('/'));
	}

	function oauth(provider: 'google' | 'github') {
		window.location.href = `/api/v1/auth/${provider}`;
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
		<h1 class={css({ fontSize: 'lg', fontWeight: 'semibold', color: 'fg.primary' })}>Sign in</h1>
		<p class={css({ fontSize: 'sm', color: 'fg.muted', marginTop: '1' })}>
			Enter your credentials to continue
		</p>
	</div>

	{#if authStore.error}
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
			{authStore.error}
		</div>
	{/if}

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

		<div>
			<label for="password" class={label({ variant: 'field' })}>Password</label>
			<input
				id="password"
				type="password"
				class={input()}
				placeholder="••••••••"
				bind:value={password}
				required
				autocomplete="current-password"
			/>
			<a
				href={resolve('/forgot-password')}
				class={css({
					display: 'block',
					fontSize: 'xs',
					color: 'accent.primary',
					textDecoration: 'underline',
					textUnderlineOffset: '2px',
					marginTop: '1',
					textAlign: 'right'
				})}
			>
				Forgot password?
			</a>
		</div>

		<button type="submit" class={button({ variant: 'primary' })} disabled={authStore.loading}>
			{#if authStore.loading}
				<div class={spinner({ size: 'sm' })}></div>
			{/if}
			Sign in
		</button>
	</form>

	<div class={css({ display: 'flex', alignItems: 'center', gap: '3' })}>
		<div class={css({ flex: '1', height: '1px', backgroundColor: 'border.primary' })}></div>
		<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>or continue with</span>
		<div class={css({ flex: '1', height: '1px', backgroundColor: 'border.primary' })}></div>
	</div>

	<div class={css({ display: 'flex', gap: '3' })}>
		<button type="button" class={cx(button(), css({ flex: '1' }))} onclick={() => oauth('google')}>
			Google
		</button>
		<button type="button" class={cx(button(), css({ flex: '1' }))} onclick={() => oauth('github')}>
			<GitBranch size={16} />
			GitHub
		</button>
	</div>

	<p class={css({ fontSize: 'sm', color: 'fg.muted', textAlign: 'center' })}>
		Don't have an account?
		<a
			href={resolve('/register')}
			class={css({
				color: 'accent.primary',
				textDecoration: 'underline',
				textUnderlineOffset: '2px'
			})}
		>
			Sign up
		</a>
	</p>
</div>
