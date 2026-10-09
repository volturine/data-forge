<script lang="ts">
	import { X, Power, LoaderCircle } from '@lucide/svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import { computeWorkersStore } from '$lib/stores/compute-workers.svelte';
	import type { ComputeWorkerStatusResponse } from '$lib/types/compute';
	import {
		computeWorkerActivityLabel,
		computeWorkerHasActiveJob,
		computeWorkerIdentityKey,
		computeWorkerShutdownConfirmText,
		computeWorkerShutdownHeading,
		computeWorkerShutdownMessage,
		computeWorkerStatusColor as statusColor
	} from '$lib/nxt/compute-worker';
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
	let pendingComputeWorker = $state<ComputeWorkerStatusResponse | null>(null);

	function requestShutdown(computeWorker: ComputeWorkerStatusResponse) {
		pendingComputeWorker = computeWorker;
		confirmOpen = true;
	}

	function cancelConfirm() {
		confirmOpen = false;
		pendingComputeWorker = null;
	}

	async function confirmShutdown() {
		const computeWorker = pendingComputeWorker;
		confirmOpen = false;
		pendingComputeWorker = null;
		if (!computeWorker) return;

		const key = computeWorkerIdentityKey(computeWorker);
		shuttingDown.add(key);
		try {
			await computeWorkersStore.shutdownComputeWorker(computeWorker);
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
			// Keep the compute workers popup open while the confirm dialog is up.
			if (confirmOpen) return;
			if (popupRef?.contains(target)) return;
			if (activeAnchor?.contains(target)) return;
			handleClose();
		}
	});

	const confirmHeading = $derived(
		pendingComputeWorker
			? computeWorkerShutdownHeading(pendingComputeWorker)
			: 'Shut down compute worker?'
	);
	const confirmMessage = $derived(
		pendingComputeWorker
			? computeWorkerShutdownMessage(pendingComputeWorker)
			: 'This will stop and remove the compute worker container.'
	);
	const confirmText = $derived(
		pendingComputeWorker ? computeWorkerShutdownConfirmText(pendingComputeWorker) : 'Shut down'
	);
</script>

{#if open}
	<div
		bind:this={popupRef}
		data-compute-workers-popup="true"
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
		aria-label="Compute workers"
		tabindex="-1"
		use:overlayStack.action={overlayConfig}
	>
		<PanelHeader>
			{#snippet title()}
				<h2
					id="compute-workers-title"
					class={css({ margin: '0', fontSize: 'sm', fontWeight: 'semibold' })}
				>
					Compute workers
				</h2>
			{/snippet}
			{#snippet actions()}
				<button
					class={iconButton({ variant: 'ghost' })}
					onclick={handleClose}
					aria-label="Close compute workers"
					type="button"
				>
					<X size={16} />
				</button>
			{/snippet}
		</PanelHeader>

		{#if computeWorkersStore.loading && computeWorkersStore.computeWorkers.length === 0}
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
				Loading compute workers...
			</div>
		{:else if computeWorkersStore.computeWorkers.length === 0}
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
				No compute workers running
			</div>
		{:else}
			<div class={css({ display: 'flex', flexDirection: 'column' })}>
				{#each computeWorkersStore.computeWorkers as computeWorker (computeWorkerIdentityKey(computeWorker))}
					{@const busy = computeWorkerHasActiveJob(computeWorker)}
					<div
						data-compute-worker-row={computeWorkerIdentityKey(computeWorker)}
						data-compute-worker-busy={busy ? 'true' : 'false'}
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
									backgroundColor: statusColor(computeWorker.status)
								})}
								title={computeWorkerActivityLabel(computeWorker)}
							></span>
							<span
								class={css({
									fontWeight: 'medium',
									overflow: 'hidden',
									textOverflow: 'ellipsis',
									whiteSpace: 'nowrap'
								})}
								title={computeWorker.resource_id}
							>
								{computeWorker.resource_id}
							</span>
							<span
								class={css({
									color: busy ? 'fg.warning' : 'fg.tertiary',
									flexShrink: '0'
								})}
								data-compute-worker-activity={busy ? 'busy' : 'idle'}
							>
								{computeWorkerActivityLabel(computeWorker)}
							</span>
						</div>
						<button
							data-compute-worker-shutdown={computeWorkerIdentityKey(computeWorker)}
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
							onclick={() => requestShutdown(computeWorker)}
							disabled={shuttingDown.has(computeWorkerIdentityKey(computeWorker))}
							type="button"
							title={busy
								? 'Cancel job and shut down compute worker'
								: 'Shut down idle compute worker'}
						>
							{#if shuttingDown.has(computeWorkerIdentityKey(computeWorker))}
								<LoaderCircle size={14} class={css({ animation: 'spin 1s linear infinite' })} />
							{:else}
								<Power size={14} />
							{/if}
						</button>
					</div>
				{/each}
			</div>
		{/if}

		{#if computeWorkersStore.error}
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
				{computeWorkersStore.error}
			</div>
		{/if}
	</div>
{/if}

<ConfirmDialog
	show={confirmOpen}
	heading={confirmHeading}
	message={confirmMessage}
	{confirmText}
	cancelText="Keep running"
	onConfirm={confirmShutdown}
	onCancel={cancelConfirm}
/>
