<script lang="ts">
	import { CheckCircle, XCircle, Save, Loader2, Database } from 'lucide-svelte';
	import { getSettings, updateSettings } from '$lib/api/settings';
	import type { AppSettings } from '$lib/api/settings';
	import { css } from '$lib/styles/panda';

	let loading = $state(true);
	let saving = $state(false);
	let feedback = $state<{ type: 'success' | 'error'; message: string } | null>(null);

	let idb = $state(false);

	// Network: load settings on mount.
	$effect(() => {
		loading = true;
		feedback = null;
		let aborted = false;
		getSettings().match(
			(s) => {
				if (aborted) return;
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

	async function save() {
		saving = true;
		feedback = null;
		const payload: Partial<AppSettings> = {
			public_idb_debug: idb
		};
		const result = await updateSettings(payload);
		result.match(
			() => {
				feedback = { type: 'success', message: 'System settings saved' };
			},
			(err) => {
				feedback = { type: 'error', message: err.message };
			}
		);
		saving = false;
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
		Loading system settings…
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
			<h2
				class={css({
					fontSize: 'md',
					fontWeight: 'semibold',
					color: 'fg.primary',
					display: 'flex',
					alignItems: 'center',
					gap: '2'
				})}
			>
				<Database size={16} />
				Debug
			</h2>

			<div
				class={css({
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'space-between'
				})}
			>
				<div class={css({ display: 'flex', flexDirection: 'column', gap: '0.5' })}>
					<span class={css({ fontSize: 'sm', fontWeight: 'medium' })}>IndexedDB Inspector</span>
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
