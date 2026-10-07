<script lang="ts">
	import { authStore } from '$lib/stores/auth.svelte';
	import { isValidTimeZone } from '$lib/utils/datetime';
	import { localTimeZone } from '$lib/utils/temporal';
	import { button, css, input, label } from '$lib/styles/panda';
	import FeedbackBanner from '$lib/components/ui/FeedbackBanner.svelte';

	const deviceTimeZone = localTimeZone();
	const supportedTimeZones = [
		'UTC',
		...new Set(
			[...Intl.supportedValuesOf('timeZone'), deviceTimeZone].filter((zone) => zone !== 'UTC')
		)
	].map((timezone) => {
		const offset = new Intl.DateTimeFormat('en-US', {
			timeZone: timezone,
			timeZoneName: 'longOffset'
		})
			.formatToParts(Date.now())
			.find((part) => part.type === 'timeZoneName')?.value;
		return { timezone, label: `${timezone} (${offset?.replace(/^GMT/, 'UTC') ?? 'UTC'})` };
	});
	const savedTimeZone = authStore.user?.preferences.timezone;
	// This form keeps a mount-time draft so background auth refreshes don't overwrite in-progress edits.
	let selectedTimeZone = $state(
		typeof savedTimeZone === 'string' && isValidTimeZone(savedTimeZone) ? savedTimeZone : ''
	);
	let saving = $state(false);
	let feedback = $state<{ kind: 'success' | 'error'; message: string } | null>(null);
	const displayTimeZone = $derived(selectedTimeZone || deviceTimeZone);

	async function savePreferences(event: SubmitEvent) {
		event.preventDefault();
		saving = true;
		feedback = null;
		if (selectedTimeZone && !isValidTimeZone(selectedTimeZone)) {
			feedback = { kind: 'error', message: 'Choose a listed time zone or use device timezone' };
			saving = false;
			return;
		}

		const preferences = { ...(authStore.user?.preferences ?? {}) };
		if (selectedTimeZone) preferences.timezone = selectedTimeZone;
		else delete preferences.timezone;

		const success = await authStore.updateProfile({ preferences });
		feedback = success
			? { kind: 'success', message: 'Preferences saved' }
			: { kind: 'error', message: authStore.error ?? 'Could not save preferences' };
		saving = false;
	}
</script>

<div class={css({ display: 'flex', flexDirection: 'column', gap: '6' })}>
	{#if feedback}
		<FeedbackBanner kind={feedback.kind} message={feedback.message} />
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
				<input
					id="timezone"
					type="text"
					class={input()}
					list="supported-timezones"
					placeholder="Search time zones"
					autocomplete="off"
					bind:value={selectedTimeZone}
					disabled={saving}
				/>
				<datalist id="supported-timezones">
					{#each supportedTimeZones as { timezone, label } (timezone)}
						<option value={timezone} {label}></option>
					{/each}
				</datalist>
				<button
					type="button"
					class={button({ variant: 'secondary', size: 'sm' })}
					onclick={() => (selectedTimeZone = '')}
					disabled={saving}
				>
					Use device timezone
				</button>
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
