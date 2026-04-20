<script lang="ts">
	import { resolve } from '$app/paths';
	import { css, button, input, label, spinner } from '$lib/styles/panda';
	import { authStore } from '$lib/stores/auth.svelte';
	import { GitBranch } from 'lucide-svelte';

	let name = $state('');
	let email = $state('');
	let password = $state('');
	let confirm = $state('');
	let validation = $state<string | null>(null);
	let registered = $state(false);

	const valid = $derived(
		password.length >= 8 && password === confirm && email.length > 0 && name.length > 0
	);

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

		const success = await authStore.register(email, password, name);
		if (success) registered = true;
	}

	function oauth(provider: 'google' | 'github') {
		window.location.href = `/api/v1/auth/${provider}`;
	}

	const displayed = $derived(validation ?? authStore.error);
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
			Create account
		</h1>
		<p class={css({ fontSize: 'sm', color: 'fg.muted', marginTop: '1' })}>
			Enter your details to get started
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

	{#if registered}
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
			Account created. Check your email for a verification link to activate your account.
		</div>

		<a href={resolve('/verify')} class={button({ variant: 'primary' })}>
			Check verification status
		</a>
	{:else}
		<form onsubmit={submit} class={css({ display: 'flex', flexDirection: 'column', gap: '4' })}>
			<div>
				<label for="name" class={label({ variant: 'field' })}>Display name</label>
				<input
					id="name"
					type="text"
					class={input()}
					placeholder="Jane Doe"
					bind:value={name}
					required
					autocomplete="name"
				/>
			</div>

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

			<button
				type="submit"
				class={button({ variant: 'primary' })}
				disabled={authStore.loading || !valid}
			>
				{#if authStore.loading}
					<div class={spinner({ size: 'sm' })}></div>
				{/if}
				Create account
			</button>
		</form>

		<div class={css({ display: 'flex', alignItems: 'center', gap: '3' })}>
			<div class={css({ flex: '1', height: '1px', backgroundColor: 'border.primary' })}></div>
			<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>or continue with</span>
			<div class={css({ flex: '1', height: '1px', backgroundColor: 'border.primary' })}></div>
		</div>

		<div class={css({ display: 'flex', gap: '3' })}>
			<button
				type="button"
				class={css({
					borderWidth: '1',
					backgroundColor: 'transparent',
					color: 'fg.primary',
					flex: '1',
					'&:hover:not(:disabled)': { backgroundColor: 'bg.hover', color: 'fg.secondary' }
				})}
				onclick={() => oauth('google')}
			>
				Google
			</button>
			<button
				type="button"
				class={css({
					borderWidth: '1',
					backgroundColor: 'transparent',
					color: 'fg.primary',
					flex: '1',
					'&:hover:not(:disabled)': { backgroundColor: 'bg.hover', color: 'fg.secondary' }
				})}
				onclick={() => oauth('github')}
			>
				<GitBranch size={16} />
				GitHub
			</button>
		</div>
	{/if}

	<p class={css({ fontSize: 'sm', color: 'fg.muted', textAlign: 'center' })}>
		Already have an account?
		<a
			href={resolve('/login')}
			class={css({
				color: 'accent.primary',
				textDecoration: 'underline',
				textUnderlineOffset: '2px'
			})}
		>
			Sign in
		</a>
	</p>
</div>
