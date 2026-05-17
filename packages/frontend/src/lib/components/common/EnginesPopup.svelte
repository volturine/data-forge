<script lang="ts">
	import { X, Power, LoaderCircle } from 'lucide-svelte';
	import { SvelteSet } from 'svelte/reactivity';
	import { enginesStore } from '$lib/stores/engines.svelte';
	import type { EngineStatus } from '$lib/types/compute';
	import PanelHeader from '$lib/components/ui/PanelHeader.svelte';
	import { css } from '$lib/styles/panda';
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

	function statusColor(status: EngineStatus): string {
		if (status === 'healthy') return 'fg.success';
		return 'fg.error';
	}

	function statusLabel(status: EngineStatus): string {
		if (status === 'healthy') return 'Healthy';
		return 'Terminated';
	}

	async function handleShutdown(analysisId: string) {
		shuttingDown.add(analysisId);
		try {
			await enginesStore.shutdownEngine(analysisId);
		} finally {
			shuttingDown.delete(analysisId);
		}
	}

	function handleClose() {
		open = false;
	}

	const overlayConfig = $derived<OverlayConfig>({
		onEscape: handleClose,
		onOutsideClick: (target: Node) => {
			if (popupRef?.contains(target)) return;
			if (activeAnchor?.contains(target)) return;
			handleClose();
		}
	});
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
					class={css({
						display: 'flex',
						cursor: 'pointer',
						alignItems: 'center',
						justifyContent: 'center',
						border: 'none',
						backgroundColor: 'transparent',
						padding: '1',
						color: 'fg.muted',
						_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' }
					})}
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
				{#each enginesStore.engines as engine (engine.analysis_id)}
					<div
						data-engine-row={engine.analysis_id}
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
								title={statusLabel(engine.status)}
							></span>
							<span
								class={css({
									fontWeight: 'medium',
									overflow: 'hidden',
									textOverflow: 'ellipsis',
									whiteSpace: 'nowrap'
								})}
								title={engine.analysis_id}
							>
								{engine.analysis_id}
							</span>
							<span class={css({ color: 'fg.tertiary', flexShrink: '0' })}>
								{statusLabel(engine.status)}
							</span>
						</div>
						<button
							data-engine-shutdown={engine.analysis_id}
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
							onclick={() => handleShutdown(engine.analysis_id)}
							disabled={shuttingDown.has(engine.analysis_id)}
							type="button"
							title="Shutdown engine"
						>
							{#if shuttingDown.has(engine.analysis_id)}
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
