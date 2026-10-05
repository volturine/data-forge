<script lang="ts">
	import type { PipelineStep } from '$lib/types/analysis';
	import { css } from '$lib/styles/panda';
	import { ChevronUp, ChevronDown, Database, ArrowDown } from '@lucide/svelte';

	interface Props {
		steps: PipelineStep[];
		canvasEl?: HTMLElement | null;
		onStepClick?: (id: string) => void;
	}

	let { steps, canvasEl = null, onStepClick }: Props = $props();

	let isExpanded = $state(true);
	let viewportTopPct = $state(0);
	let viewportHeightPct = $state(100);

	const stepCountLabel = $derived(`${steps.length} ${steps.length === 1 ? 'step' : 'steps'}`);

	function updateViewport() {
		if (!canvasEl) {
			viewportTopPct = 0;
			viewportHeightPct = 100;
			return;
		}
		const { scrollTop, scrollHeight, clientHeight } = canvasEl;
		if (scrollHeight <= clientHeight || scrollHeight === 0) {
			viewportTopPct = 0;
			viewportHeightPct = 100;
			return;
		}
		const top = (scrollTop / scrollHeight) * 100;
		const height = Math.max(10, (clientHeight / scrollHeight) * 100);
		viewportTopPct = Math.min(top, 100 - height);
		viewportHeightPct = height;
	}

	function scrollToTarget(selector: string) {
		if (!canvasEl) return;
		const target = canvasEl.querySelector(selector) as HTMLElement | null;
		if (target) {
			target.scrollIntoView({ behavior: 'smooth', block: 'center' });
		}
	}

	function handleDatasourceClick() {
		scrollToTarget('#pipeline-datasource-node');
	}

	function handleStepClick(id: string) {
		scrollToTarget(`#step-node-${id}`);
		onStepClick?.(id);
	}

	function handleOutputClick() {
		scrollToTarget('#pipeline-output-node');
	}

	$effect(() => {
		if (!canvasEl) return;
		updateViewport();
		canvasEl.addEventListener('scroll', updateViewport, { passive: true });
		window.addEventListener('resize', updateViewport, { passive: true });

		return () => {
			canvasEl?.removeEventListener('scroll', updateViewport);
			window.removeEventListener('resize', updateViewport);
		};
	});
</script>

<div
	class={css({
		position: 'absolute',
		top: '4',
		right: '4',
		zIndex: '10',
		display: 'flex',
		flexDirection: 'column',
		alignItems: 'flex-end',
		gap: '2',
		pointerEvents: 'none'
	})}
	data-testid="pipeline-minimap-container"
>
	<!-- Step Count & Toggle Header -->
	<div
		class={css({
			display: 'flex',
			alignItems: 'center',
			gap: '2',
			backgroundColor: 'bg.primary',
			borderWidth: '1',
			borderColor: 'border.secondary',
			borderRadius: 'md',
			boxShadow: 'sm',
			paddingX: '2.5',
			paddingY: '1.5',
			pointerEvents: 'auto'
		})}
	>
		<span
			data-testid="canvas-step-count"
			class={css({
				fontSize: 'xs',
				fontWeight: 'semibold',
				color: 'fg.secondary',
				letterSpacing: 'wide'
			})}
		>
			{stepCountLabel}
		</span>
		<button
			type="button"
			data-testid="minimap-toggle"
			aria-label={isExpanded ? 'Collapse minimap' : 'Expand minimap'}
			title={isExpanded ? 'Collapse minimap' : 'Expand minimap'}
			onclick={() => (isExpanded = !isExpanded)}
			class={css({
				display: 'inline-flex',
				alignItems: 'center',
				justifyContent: 'center',
				background: 'none',
				border: 'none',
				padding: '0.5',
				cursor: 'pointer',
				color: 'fg.muted',
				_hover: { color: 'fg.primary' }
			})}
		>
			{#if isExpanded}
				<ChevronUp size={14} />
			{:else}
				<ChevronDown size={14} />
			{/if}
		</button>
	</div>

	<!-- Minimap body -->
	{#if isExpanded}
		<div
			data-testid="pipeline-minimap"
			class={css({
				width: '44',
				maxHeight: '80',
				backgroundColor: 'bg.primary',
				borderWidth: '1',
				borderColor: 'border.secondary',
				borderRadius: 'md',
				boxShadow: 'md',
				padding: '2.5',
				display: 'flex',
				flexDirection: 'column',
				gap: '2',
				pointerEvents: 'auto',
				overflow: 'hidden'
			})}
		>
			<!-- Rail container with relative positioning for viewport indicator -->
			<div
				class={css({
					position: 'relative',
					display: 'flex',
					flexDirection: 'column',
					gap: '1.5',
					maxHeight: '64',
					overflowY: 'auto',
					paddingRight: '1'
				})}
			>
				<!-- Viewport indicator overlay -->
				<div
					data-testid="minimap-viewport-indicator"
					class={css({
						position: 'absolute',
						left: '0',
						right: '0',
						borderWidth: '1',
						borderColor: 'border.accent',
						backgroundColor: 'bg.tertiary',
						opacity: '0.3',
						pointerEvents: 'none',
						borderRadius: 'xs',
						transitionProperty: 'top, height',
						transitionDuration: '75ms'
					})}
					style={`top: ${viewportTopPct}%; height: ${viewportHeightPct}%;`}
				></div>

				<!-- Datasource Node -->
				<button
					type="button"
					data-testid="minimap-datasource"
					onclick={handleDatasourceClick}
					class={css({
						display: 'flex',
						alignItems: 'center',
						gap: '1.5',
						width: 'full',
						paddingX: '2',
						paddingY: '1',
						fontSize: '2xs',
						fontWeight: 'medium',
						color: 'fg.secondary',
						backgroundColor: 'bg.secondary',
						borderWidth: '1',
						borderColor: 'border.subtle',
						borderRadius: 'xs',
						textAlign: 'left',
						cursor: 'pointer',
						_hover: { backgroundColor: 'bg.hover', borderColor: 'border.secondary' }
					})}
				>
					<Database size={12} class={css({ flexShrink: '0', color: 'accent.primary' })} />
					<span class={css({ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' })}>
						Source
					</span>
				</button>

				<!-- Steps -->
				{#each steps as step, i (step.id)}
					<button
						type="button"
						data-testid={`minimap-step-${step.id}`}
						onclick={() => handleStepClick(step.id)}
						class={css({
							display: 'flex',
							alignItems: 'center',
							gap: '1.5',
							width: 'full',
							paddingX: '2',
							paddingY: '1',
							fontSize: '2xs',
							color: step.is_applied === false ? 'fg.faint' : 'fg.primary',
							backgroundColor: step.is_applied === false ? 'bg.secondary' : 'bg.primary',
							borderWidth: '1',
							borderColor: 'border.subtle',
							borderStyle: step.is_applied === false ? 'dashed' : 'solid',
							borderRadius: 'xs',
							textAlign: 'left',
							cursor: 'pointer',
							_hover: { backgroundColor: 'bg.hover', borderColor: 'border.secondary' }
						})}
					>
						<span
							class={css({
								fontSize: '3xs',
								color: 'fg.muted',
								fontFamily: 'mono',
								width: '3.5',
								flexShrink: '0'
							})}
						>
							{i + 1}
						</span>
						<span
							class={css({
								overflow: 'hidden',
								textOverflow: 'ellipsis',
								whiteSpace: 'nowrap',
								textTransform: 'capitalize'
							})}
						>
							{step.type}
						</span>
					</button>
				{/each}

				<!-- Output Node -->
				<button
					type="button"
					data-testid="minimap-output"
					onclick={handleOutputClick}
					class={css({
						display: 'flex',
						alignItems: 'center',
						gap: '1.5',
						width: 'full',
						paddingX: '2',
						paddingY: '1',
						fontSize: '2xs',
						fontWeight: 'medium',
						color: 'fg.secondary',
						backgroundColor: 'bg.secondary',
						borderWidth: '1',
						borderColor: 'border.subtle',
						borderRadius: 'xs',
						textAlign: 'left',
						cursor: 'pointer',
						_hover: { backgroundColor: 'bg.hover', borderColor: 'border.secondary' }
					})}
				>
					<ArrowDown size={12} class={css({ flexShrink: '0', color: 'accent.primary' })} />
					<span class={css({ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' })}>
						Output
					</span>
				</button>
			</div>
		</div>
	{/if}
</div>
