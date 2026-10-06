<script lang="ts">
	import { authStore } from '$lib/stores/auth.svelte';
	import { isValidTimeZone } from '$lib/utils/datetime';
	import { localTimeZone } from '$lib/utils/temporal';
	import { button, css, label } from '$lib/styles/panda';

	const deviceTimeZone = localTimeZone();
	const supportedTimeZones = [
		'UTC',
		...new Set(
			[...Intl.supportedValuesOf('timeZone'), deviceTimeZone].filter((zone) => zone !== 'UTC')
		)
	];
	const savedTimeZone = authStore.user?.preferences.timezone;
	let selectedTimeZone = $state(
		typeof savedTimeZone === 'string' && isValidTimeZone(savedTimeZone) ? savedTimeZone : ''
	);
	let saving = $state(false);
	let feedback = $state<{ type: 'success' | 'error'; message: string } | null>(null);
	const displayTimeZone = $derived(selectedTimeZone || deviceTimeZone);

	async function savePreferences(event: SubmitEvent) {
		event.preventDefault();
		saving = true;
		feedback = null;

		const preferences = { ...(authStore.user?.preferences ?? {}) };
		if (selectedTimeZone) preferences.timezone = selectedTimeZone;
		else delete preferences.timezone;

		const success = await authStore.updateProfile({ preferences });
		feedback = success
			? { type: 'success', message: 'Preferences saved' }
			: { type: 'error', message: authStore.error ?? 'Could not save preferences' };
		saving = false;
	}
</script>

<div class={css({ display: 'flex', flexDirection: 'column', gap: '6' })}>
	{#if feedback}
		<div
			class={css({
				borderWidth: '1',
				padding: '2',
				fontSize: 'sm',
				...(feedback.type === 'success'
					? {
							borderColor: 'border.success',
							backgroundColor: 'bg.success',
							color: 'fg.success'
						}
					: { borderColor: 'border.error', backgroundColor: 'bg.error', color: 'fg.error' })
			})}
			role={feedback.type === 'error' ? 'alert' : 'status'}
		>
			{feedback.message}
		</div>
	{/if}

	<section
		class={css({
			backgroundColor: 'bg.panel',
			borderWidth: '1',
			padding: '6',
			display: 'flex',
			flexDirection: 'column',
			gap: '5'
		})}
	>
		<div>
			<h2
				class={css({
					fontSize: 'md',
					fontWeight: 'semibold',
					color: 'fg.primary',
					paddingBottom: '3',
					borderBottomWidth: '1',
					borderColor: 'border.primary'
				})}
			>
				Regional
			</h2>
			<p class={css({ fontSize: 'sm', color: 'fg.muted', marginTop: '3' })}>
				Timestamps are stored in UTC and shown in your selected timezone.
			</p>
		</div>

		<form
			onsubmit={savePreferences}
			class={css({ display: 'flex', flexDirection: 'column', gap: '4' })}
		>
			<div>
				<label for="timezone" class={label({ variant: 'field' })}>Time zone</label>
				<select
					id="timezone"
					class={css({
						width: 'full',
						fontSize: 'sm2',
						color: 'fg.primary',
						backgroundColor: 'bg.primary',
						borderWidth: '1',
						borderRadius: '0',
						paddingX: '3.5',
						paddingY: '2.25',
						_focus: { outline: 'none', borderColor: 'border.accent' },
						_disabled: { opacity: '0.5', cursor: 'not-allowed', backgroundColor: 'bg.tertiary' }
					})}
					bind:value={selectedTimeZone}
					disabled={saving}
				>
					<option value="">Use device timezone ({deviceTimeZone})</option>
					{#each supportedTimeZones as timezone (timezone)}
						<option value={timezone}>{timezone}</option>
					{/each}
				</select>
				<p class={css({ fontSize: 'xs', color: 'fg.tertiary', marginTop: '1' })}>
					Currently showing times in {displayTimeZone}.
				</p>
			</div>

			<div class={css({ display: 'flex', justifyContent: 'flex-end' })}>
				<button type="submit" class={button({ variant: 'primary' })} disabled={saving}>
					{saving ? 'Saving…' : 'Save preferences'}
				</button>
			</div>
		</form>
	</section>
</div>
