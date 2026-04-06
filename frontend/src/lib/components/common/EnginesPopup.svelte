<script lang="ts">
	import { X, Power, Loader2 } from 'lucide-svelte';
	import { enginesStore } from '$lib/stores/engines.svelte';
	import type { EngineStatus } from '$lib/types/compute';
	import PanelHeader from '$lib/components/ui/PanelHeader.svelte';
	import { css, cx, row } from '$lib/styles/panda';

	interface Props {
		open: boolean;
		anchor?: HTMLElement | null;
	}

	let { open = $bindable(), anchor = null }: Props = $props();

	let shuttingDown = $state<Set<string>>(new Set());
	let popoverRect = $state({ left: 0, bottom: 0, width: 320 });
	let lastAnchor = $state<HTMLElement | null>(null);

	function statusColor(status: EngineStatus): string {
		if (status === 'healthy') return 'fg.success';
		return 'fg.error';
	}

	function statusLabel(status: EngineStatus): string {
		if (status === 'healthy') return 'Healthy';
		return 'Terminated';
	}

	async function handleShutdown(analysisId: string) {
		shuttingDown = new Set([...shuttingDown, analysisId]);
		try {
			await enginesStore.shutdownEngine(analysisId);
		} finally {
			shuttingDown = new Set([...shuttingDown].filter((id) => id !== analysisId));
		}
	}

	function handleClose() {
		open = false;
	}

	function handleKeydown(event: KeyboardEvent) {
		if (!open) return;
		if (event.key === 'Escape') handleClose();
	}

	function handleBackdropKeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' || event.key === ' ') {
			event.preventDefault();
			handleClose();
		}
	}

	function updatePopoverPosition() {
		const node = lastAnchor;
		if (!node) return;
		const rect = node.getBoundingClientRect();
		const width = 320;
		popoverRect = {
			left: rect.right + 6,
			bottom: window.innerHeight - rect.bottom,
			width
		};
	}

	function applyPopoverPosition(
		node: HTMLElement | undefined,
		rect: { left: number; bottom: number; width: number }
	) {
		if (!node) return;
		node.style.left = `${rect.left}px`;
		node.style.bottom = `${rect.bottom}px`;
		node.style.width = `${rect.width}px`;
	}

	function portal(node: HTMLElement, rect: { left: number; bottom: number; width: number }) {
		document.body.appendChild(node);
		applyPopoverPosition(node, rect);
		return {
			update(next: { left: number; bottom: number; width: number }) {
				applyPopoverPosition(node, next);
			},
			destroy() {
				node.remove();
			}
		};
	}

	// DOM: $derived can't track anchor position.
	$effect(() => {
		if (!open) return;
		lastAnchor = anchor;
		if (!lastAnchor) return;
		updatePopoverPosition();
		const handleResize = () => updatePopoverPosition();
		window.addEventListener('resize', handleResize);
		window.addEventListener('scroll', handleResize, true);
		return () => {
			window.removeEventListener('resize', handleResize);
			window.removeEventListener('scroll', handleResize, true);
		};
	});

	// Network: fetch engines when popup opens; $derived cannot trigger side effects.
	$effect(() => {
		if (!open) return;
		enginesStore.fetch();
	});
</script>

<svelte:window onkeydown={handleKeydown} />

{#if open}
	<div
		class={css({
			position: 'fixed',
			inset: '0',
			zIndex: 'popover',
			backgroundColor: 'transparent'
		})}
		onclick={handleClose}
		onkeydown={handleBackdropKeydown}
		role="button"
		tabindex="0"
		aria-label="Close engines"
	></div>
	<div
		class={css({
			position: 'fixed',
			zIndex: 'overlay',
			display: 'flex',
			flexDirection: 'column',
			borderWidth: '1',
			backgroundColor: 'bg.primary',
			boxShadow: 'drag',
			outline: 'none',
			maxHeight: '60vh',
			overflowY: 'auto'
		})}
		role="dialog"
		aria-modal="false"
		aria-labelledby="engines-title"
		tabindex="-1"
		use:portal={popoverRect}
		onclick={(e) => e.stopPropagation()}
		onkeydown={(e) => e.stopPropagation()}
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
				<Loader2 size={14} class={css({ animation: 'spin 1s linear infinite' })} />
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
						<div class={cx(row, css({ gap: '2', minWidth: '0' }))}>
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
								<Loader2 size={14} class={css({ animation: 'spin 1s linear infinite' })} />
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
