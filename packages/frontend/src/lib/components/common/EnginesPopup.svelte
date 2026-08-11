<script lang="ts">
	import { X, Power, LoaderCircle } from '@lucide/svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import { enginesStore } from '$lib/stores/engines.svelte';
	import type { EngineStatusResponse } from '$lib/types/compute';
	import {
		engineActivityLabel,
		engineHasActiveJob,
		engineIdentityKey,
		engineShutdownConfirmText,
		engineShutdownHeading,
		engineShutdownMessage,
		engineStatusColor as statusColor
	} from '$lib/nxt/engine';
	import PanelHeader from '$lib/components/ui/PanelHeader.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import { css, iconButton } from '$lib/styles/panda';
	import { overlayStack } from '$lib/stores/overlay.svelte';
	import type { OverlayConfig } from '$lib/stores/overlay.svelte';

	interface Props {
		open: boolean;
		anchor?: HTMLElement | null;
	}

	let { open = $bindable(), anchor = null }: Props = $props();

	const shuttingDown = new SvelteSet<string>();
	let popupRef = $state<HTMLElement | null>(null);
	const activeAnchor = $derived(open ? anchor : null);

	let confirmOpen = $state(false);
	let pendingEngine = $state<EngineStatusResponse | null>(null);

	function requestShutdown(engine: EngineStatusResponse) {
		pendingEngine = engine;
		confirmOpen = true;
	}

	function cancelConfirm() {
		confirmOpen = false;
		pendingEngine = null;
	}

	async function confirmShutdown() {
		const engine = pendingEngine;
		confirmOpen = false;
		pendingEngine = null;
		if (!engine) return;

		const key = engineIdentityKey(engine);
		shuttingDown.add(key);
		try {
			await enginesStore.shutdownEngine(engine);
		} finally {
			shuttingDown.delete(key);
		}
	}

	function handleClose() {
		open = false;
	}

	const overlayConfig = $derived<OverlayConfig>({
		onEscape: handleClose,
		onOutsideClick: (target: Node) => {
			// Keep engines popup open while the confirm dialog is up.
			if (confirmOpen) return;
			if (popupRef?.contains(target)) return;
			if (activeAnchor?.contains(target)) return;
			handleClose();
		}
	});

	const confirmHeading = $derived(
		pendingEngine ? engineShutdownHeading(pendingEngine) : 'Shut down engine?'
	);
	const confirmMessage = $derived(
		pendingEngine
			? engineShutdownMessage(pendingEngine)
			: 'This will stop and remove the engine container.'
	);
	const confirmText = $derived(
		pendingEngine ? engineShutdownConfirmText(pendingEngine) : 'Shut down'
	);
</script>

{#if open}
	<div
		bind:this={popupRef}
		data-engines-popup="true"
		class={css({
			position: 'absolute',
			left: '0',
			bottom: 'calc(100% + 6px)',
			zIndex: 'overlay',
			display: 'flex',
			flexDirection: 'column',
			borderWidth: '1',
			backgroundColor: 'bg.primary',
			boxShadow: 'drag',
			outline: 'none',
			width: 'panel',
			maxWidth: 'calc(100vw - 24px)',
			maxHeight: '60vh',
			overflowY: 'auto'
		})}
		role="dialog"
		aria-modal="false"
		aria-label="Engines"
		tabindex="-1"
		use:overlayStack.action={overlayConfig}
	>
		<PanelHeader>
			{#snippet title()}
				<h2 id="engines-title" class={css({ margin: '0', fontSize: 'sm', fontWeight: 'semibold' })}>
					Engines
				</h2>
			{/snippet}
			{#snippet actions()}
				<button
					class={iconButton({ variant: 'ghost' })}
					onclick={handleClose}
					aria-label="Close engines"
					type="button"
				>
					<X size={16} />
				</button>
			{/snippet}
		</PanelHeader>

		{#if enginesStore.loading && enginesStore.engines.length === 0}
			<div
				class={css({
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'center',
					gap: '2',
					padding: '8',
					fontSize: 'xs',
					color: 'fg.muted'
				})}
			>
				<LoaderCircle size={14} class={css({ animation: 'spin 1s linear infinite' })} />
				Loading engines...
			</div>
		{:else if enginesStore.engines.length === 0}
			<div
				class={css({
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'center',
					padding: '8',
					fontSize: 'xs',
					color: 'fg.muted'
				})}
			>
				No engines running
			</div>
		{:else}
			<div class={css({ display: 'flex', flexDirection: 'column' })}>
				{#each enginesStore.engines as engine (engineIdentityKey(engine))}
					{@const busy = engineHasActiveJob(engine)}
					<div
						data-engine-row={engineIdentityKey(engine)}
						data-engine-busy={busy ? 'true' : 'false'}
						class={css({
							display: 'flex',
							alignItems: 'center',
							justifyContent: 'space-between',
							borderBottomWidth: '1',
							paddingX: '4',
							paddingY: '3',
							fontSize: 'xs'
						})}
					>
						<div class={css({ display: 'flex', alignItems: 'center', gap: '2', minWidth: '0' })}>
							<span
								class={css({
									display: 'inline-block',
									height: 'dot',
									width: 'dot',
									flexShrink: '0',
									backgroundColor: statusColor(engine.status)
								})}
								title={engineActivityLabel(engine)}
							></span>
							<span
								class={css({
									fontWeight: 'medium',
									overflow: 'hidden',
									textOverflow: 'ellipsis',
									whiteSpace: 'nowrap'
								})}
								title={engine.resource_id}
							>
								{engine.resource_id}
							</span>
							<span
								class={css({
									color: busy ? 'fg.warning' : 'fg.tertiary',
									flexShrink: '0'
								})}
								data-engine-activity={busy ? 'busy' : 'idle'}
							>
								{engineActivityLabel(engine)}
							</span>
						</div>
						<button
							data-engine-shutdown={engineIdentityKey(engine)}
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
								_hover: { color: 'error' },
								_disabled: { cursor: 'not-allowed', opacity: 0.5 }
							})}
							onclick={() => requestShutdown(engine)}
							disabled={shuttingDown.has(engineIdentityKey(engine))}
							type="button"
							title={busy ? 'Cancel job and shut down engine' : 'Shut down idle engine'}
						>
							{#if shuttingDown.has(engineIdentityKey(engine))}
								<LoaderCircle size={14} class={css({ animation: 'spin 1s linear infinite' })} />
							{:else}
								<Power size={14} />
							{/if}
						</button>
					</div>
				{/each}
			</div>
		{/if}

		{#if enginesStore.error}
			<div
				class={css({
					display: 'flex',
					alignItems: 'center',
					gap: '2',
					borderTopWidth: '1',
					paddingX: '4',
					paddingY: '3',
					fontSize: 'xs',
					color: 'fg.error'
				})}
			>
				{enginesStore.error}
			</div>
		{/if}
	</div>
{/if}

<ConfirmDialog
	show={confirmOpen}
	heading={confirmHeading}
	message={confirmMessage}
	confirmText={confirmText}
	cancelText="Keep running"
	onConfirm={confirmShutdown}
	onCancel={cancelConfirm}
/>
