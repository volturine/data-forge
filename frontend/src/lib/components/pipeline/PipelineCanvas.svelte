<script lang="ts">
	import type { PipelineStep, AnalysisTab } from '$lib/types/analysis';
	import type { DataSource } from '$lib/types/datasource';
	import { drag, type DropTarget } from '$lib/stores/drag.svelte';
	import { LayoutGrid } from 'lucide-svelte';
	import StepNode from './StepNode.svelte';
	import OutputNode from './OutputNode.svelte';
	import ConnectionLine from './ConnectionLine.svelte';
	import DatasourceNode from './DatasourceNode.svelte';
	import { css, cx } from '$lib/styles/panda';

	interface Props {
		steps: PipelineStep[];
		analysisId?: string;
		datasourceId?: string;
		datasource?: DataSource | null;
		datasourceLabel?: string | null;
		tabName?: string;
		activeTab?: AnalysisTab | null;
		onStepClick: (id: string) => void;
		onStepDelete: (id: string) => void;
		onStepToggle: (id: string) => void;
		onInsertStep: (type: string, target: DropTarget) => void;
		onMoveStep: (stepId: string, target: DropTarget) => void;
		onChangeDatasource?: () => void;
		onRenameTab?: (name: string) => void;
	}

	let {
		steps,
		analysisId,
		datasourceId,
		datasource = null,
		datasourceLabel = null,
		tabName: _tabName,
		activeTab = null,
		onStepClick,
		onStepDelete,
		onStepToggle,
		onInsertStep,
		onMoveStep,
		onChangeDatasource: _onChangeDatasource,
		onRenameTab: _onRenameTab
	}: Props = $props();

	const canDrop = $derived(drag.active);
	const hoverIndex = $derived(drag.target?.index ?? null);
	const activeTabId = $derived(activeTab?.id ?? null);

	let lastTabId = $state<string | null>(null);

	// $effect: drag reset is a UI side effect not derivable from state
	// Subscription: $derived can't reset drag UI on tab change.
	$effect(() => {
		const tabId = activeTabId;
		if (tabId === lastTabId) return;
		lastTabId = tabId;
		if (drag.active) {
			drag.end();
			return;
		}
		drag.clearTarget();
	});

	function buildTarget(index: number): DropTarget {
		return {
			index,
			parentId: index === 0 ? null : (steps[index - 1]?.id ?? null),
			nextId: steps[index]?.id ?? null
		};
	}

	function shouldShowInsert(index: number): boolean {
		if (!drag.isReorder || !drag.stepId) return true;
		const currentIndex = steps.findIndex((step) => step.id === drag.stepId);
		if (currentIndex === -1) return true;
		return index !== currentIndex && index !== currentIndex + 1;
	}

	function isValidTarget(index: number): boolean {
		// For reorder operations, check if we're dropping on ourselves
		if (drag.isReorder && drag.stepId) {
			const currentIndex = steps.findIndex((s) => s.id === drag.stepId);
			// Can't drop on self (same position or adjacent)
			if (index === currentIndex || index === currentIndex + 1) {
				return false;
			}
		}

		if (drag.type === 'chart' || drag.type?.startsWith('plot_')) {
			return true;
		}

		const nextId = steps[index]?.id ?? null;
		if (!nextId) return true;

		// For reorder, the next step might be the one we're moving
		if (drag.isReorder && nextId === drag.stepId) {
			return true;
		}

		const nextStep = steps.find((s) => s.id === nextId);
		if (!nextStep) return true;
		const deps = nextStep.depends_on ?? [];
		// Valid if no dependencies or single dependency matching expected parent
		if (deps.length === 0) return true;
		if (deps.length > 1) return false;
		const parentId = index === 0 ? null : (steps[index - 1]?.id ?? null);
		return deps[0] === parentId;
	}

	function handleDragEnter(event: DragEvent, index: number) {
		if (!drag.active) return;
		event.preventDefault();
		const target = buildTarget(index);
		const valid = isValidTarget(index);
		drag.setTarget(target, valid);
	}

	function handleDragOver(event: DragEvent) {
		if (drag.active) {
			event.preventDefault();
			if (event.dataTransfer) {
				event.dataTransfer.dropEffect = drag.isReorder ? 'move' : 'copy';
			}
		}
	}

	function handleDragLeave(event: DragEvent) {
		const related = event.relatedTarget as Node | null;
		const current = event.currentTarget as Node;
		if (!related || !current.contains(related)) {
			drag.clearTarget();
		}
	}

	function handleDrop(event: DragEvent, index: number) {
		event.preventDefault();
		if (!drag.active) return;

		const target = buildTarget(index);
		const valid = isValidTarget(index);

		if (!valid) {
			drag.end();
			return;
		}

		if (drag.isReorder && drag.stepId) {
			// Moving existing step
			onMoveStep(drag.stepId, target);
		} else if (drag.isInsert && drag.type) {
			// Inserting new step from library
			onInsertStep(drag.type, target);
		}

		drag.end();
	}

	function resolveTargetFromPoint(x: number, y: number): DropTarget | null {
		const zones = Array.from(document.querySelectorAll<HTMLElement>('.insert-zone'));
		const entries = zones
			.map((zone) => {
				const raw = zone.dataset.index;
				const index = raw ? Number(raw) : Number.NaN;
				const rect = zone.getBoundingClientRect();
				return {
					index,
					rect,
					center: rect.top + rect.height / 2
				};
			})
			.filter((item) => Number.isFinite(item.index));

		const entry = entries.find((item) => y >= item.rect.top && y <= item.rect.bottom);
		if (entry) return buildTarget(entry.index);

		const sorted = entries
			.filter((item) => Number.isFinite(item.center))
			.sort((a, b) => a.center - b.center);

		const fallback = sorted.find((item) => y < item.center) ?? sorted.at(-1);
		if (!fallback) return null;

		return buildTarget(fallback.index);
	}

	// DOM: $derived can't update drop target from pointer.
	$effect(() => {
		if (!drag.active) return;
		if (drag.pointerX === null || drag.pointerY === null) return;
		const target = resolveTargetFromPoint(drag.pointerX, drag.pointerY);
		if (!target) {
			drag.clearTarget();
			return;
		}
		const valid = isValidTarget(target.index);
		drag.setTarget(target, valid);
	});

	const scrollThreshold = 60;
	const scrollSpeed = 15;

	function autoScroll(canvasEl: HTMLElement, pointerY: number) {
		const viewportHeight = window.innerHeight;

		if (pointerY > viewportHeight - scrollThreshold) {
			canvasEl.scrollTop += scrollSpeed;
		}

		if (pointerY < scrollThreshold) {
			canvasEl.scrollTop -= scrollSpeed;
		}
	}

	// DOM: $derived can't auto-scroll while dragging.
	$effect(() => {
		if (!drag.active) return;
		if (drag.pointerY === null) return;

		const canvas = document.querySelector('.pipeline-canvas') as HTMLElement | null;
		if (!canvas) return;

		const handleScroll = () => {
			if (!drag.active || drag.pointerY === null) return;
			autoScroll(canvas, drag.pointerY);
		};

		const intervalId = window.setInterval(handleScroll, 16);
		return () => window.clearInterval(intervalId);
	});
</script>

<div
	class={cx(
		'pipeline-canvas',
		css({
			flex: '1',
			overflowY: 'auto',
			padding: '8',
			backgroundColor: 'bg.secondary',
			minHeight: 'panel'
		})
	)}
>
	{#if steps.length === 0}
		<div
			class={css({
				display: 'flex',
				minHeight: 'panel',
				height: '100%',
				flexDirection: 'column',
				alignItems: 'center',
				justifyContent: 'center',
				textAlign: 'center',
				color: 'fg.muted'
			})}
		>
			<LayoutGrid
				size={28}
				strokeWidth={1.2}
				class={css({ marginBottom: '5', color: 'fg.faint', opacity: '0.4' })}
			/>
			<h3
				class={css({
					margin: '0',
					marginBottom: '2',
					fontSize: 'sm',
					fontWeight: '600',
					color: 'fg.secondary'
				})}
			>
				No pipeline steps
			</h3>
			<p class={css({ margin: '0', fontSize: 'xs', color: 'fg.muted' })}>
				Drag operations from the library and drop here
			</p>
			<div
				class={cx(
					'insert-zone',
					css({
						display: 'flex',
						width: '100%',
						cursor: canDrop ? 'pointer' : 'default',
						flexDirection: 'column',
						alignItems: 'center',
						paddingY: '2'
					})
				)}
				class:ready={canDrop}
				role="button"
				tabindex="0"
				data-index="0"
				ondragenter={(e) => handleDragEnter(e, 0)}
				ondragover={handleDragOver}
				ondragleave={handleDragLeave}
				ondrop={(e) => handleDrop(e, 0)}
			>
				{#if steps.length > 0 || canDrop}
					<ConnectionLine
						fromStepIndex={-1}
						toStepIndex={0}
						totalSteps={steps.length + 1}
						highlighted={hoverIndex === 0}
					/>
				{/if}

				{#if canDrop}
					<div
						class={css({
							marginY: '2',
							display: 'flex',
							minHeight: 'row',
							width: 'min(55%, 480px)',
							flexShrink: '0',
							alignItems: 'center',
							justifyContent: 'center',
							borderWidth: '2',
							borderStyle: 'dashed',
							paddingX: '4',
							paddingY: '2',
							textAlign: 'center',
							borderColor: hoverIndex === 0 && !drag.valid ? 'error.border' : 'border.primary',
							backgroundColor:
								hoverIndex === 0 && !drag.valid
									? 'error.bg'
									: hoverIndex === 0
										? 'bg.tertiary'
										: 'transparent',
							_hover: { backgroundColor: 'bg.hover' }
						})}
					>
						{#if hoverIndex === 0}
							<span
								class={css({
									fontFamily: 'mono',
									fontSize: 'sm',
									fontWeight: '500',
									textTransform: 'lowercase'
								})}>{drag.type ?? 'step'}</span
							>
						{/if}
					</div>
					<ConnectionLine
						fromStepIndex={-1}
						toStepIndex={0}
						totalSteps={steps.length + 1}
						highlighted={hoverIndex === 0}
					/>
				{/if}
			</div>
		</div>
	{:else}
		<div
			class={css({
				marginX: 'auto',
				display: 'flex',
				width: '100%',
				maxWidth: '100%',
				flexDirection: 'column',
				alignItems: 'center'
			})}
			role="list"
		>
			<DatasourceNode
				{datasource}
				{datasourceLabel}
				{analysisId}
				tabName={_tabName}
				{activeTab}
				onChangeDatasource={_onChangeDatasource}
				onRenameTab={_onRenameTab}
			/>
			{#if shouldShowInsert(0) && (steps.length > 0 || canDrop)}
				<div
					class={cx(
						'insert-zone',
						css({
							display: 'flex',
							width: '100%',
							cursor: canDrop ? 'pointer' : 'default',
							flexDirection: 'column',
							alignItems: 'center',
							paddingY: '2'
						})
					)}
					class:ready={canDrop}
					role="button"
					tabindex="0"
					data-index="0"
					ondragenter={(e) => handleDragEnter(e, 0)}
					ondragover={handleDragOver}
					ondragleave={handleDragLeave}
					ondrop={(e) => handleDrop(e, 0)}
				>
					<ConnectionLine
						fromStepIndex={-1}
						toStepIndex={0}
						totalSteps={steps.length + 1}
						highlighted={hoverIndex === 0}
					/>
					{#if canDrop}
						<div
							class={css({
								marginY: '2',
								display: 'flex',
								minHeight: 'row',
								width: 'min(55%, 480px)',
								flexShrink: '0',
								alignItems: 'center',
								justifyContent: 'center',
								borderWidth: '2',
								borderStyle: 'dashed',
								paddingX: '4',
								paddingY: '2',
								textAlign: 'center',
								borderColor: hoverIndex === 0 && !drag.valid ? 'error.border' : 'border.primary',
								backgroundColor:
									hoverIndex === 0 && !drag.valid
										? 'error.bg'
										: hoverIndex === 0
											? 'bg.tertiary'
											: 'transparent',
								_hover: { backgroundColor: 'bg.hover' }
							})}
						>
							{#if hoverIndex === 0}
								<span
									class={css({
										fontFamily: 'mono',
										fontSize: 'sm',
										fontWeight: '500',
										textTransform: 'lowercase'
									})}>{drag.type ?? 'step'}</span
								>
							{/if}
						</div>
						{#if steps.length > 0}
							<ConnectionLine
								fromStepIndex={-1}
								toStepIndex={0}
								totalSteps={steps.length + 1}
								highlighted={hoverIndex === 0}
							/>
						{/if}
					{/if}
				</div>
			{:else if steps.length > 0}
				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'center',
						paddingY: '2'
					})}
					aria-hidden="true"
				>
					<ConnectionLine fromStepIndex={-1} toStepIndex={0} totalSteps={steps.length} />
				</div>
			{/if}
			{#each steps as step, i (step.id)}
				<StepNode
					{step}
					index={i}
					{analysisId}
					{datasourceId}
					allSteps={steps}
					onEdit={onStepClick}
					onDelete={onStepDelete}
					onToggleApply={onStepToggle}
					onTouchMove={onMoveStep}
				/>
				<!-- Connection + Drop zone after each step -->
				{#if i < steps.length - 1 || canDrop}
					{#if shouldShowInsert(i + 1)}
						<div
							class={cx(
								'insert-zone',
								css({
									display: 'flex',
									width: '100%',
									cursor: canDrop ? 'pointer' : 'default',
									flexDirection: 'column',
									alignItems: 'center',
									paddingY: '2'
								})
							)}
							class:ready={canDrop}
							role="button"
							tabindex="0"
							data-index={i + 1}
							ondragenter={(e) => handleDragEnter(e, i + 1)}
							ondragover={handleDragOver}
							ondragleave={handleDragLeave}
							ondrop={(e) => handleDrop(e, i + 1)}
						>
							{#if i < steps.length - 1 || !drag.isReorder || drag.stepId !== step.id}
								<ConnectionLine
									fromStepIndex={i}
									toStepIndex={i + 1}
									totalSteps={steps.length}
									highlighted={hoverIndex === i + 1}
								/>
							{/if}
							{#if canDrop}
								<div
									class={css({
										marginY: '2',
										display: 'flex',
										minHeight: 'row',
										width: 'min(55%, 480px)',
										flexShrink: '0',
										alignItems: 'center',
										justifyContent: 'center',
										borderWidth: '2',
										borderStyle: 'dashed',
										paddingX: '4',
										paddingY: '2',
										textAlign: 'center',
										borderColor:
											hoverIndex === i + 1 && !drag.valid ? 'error.border' : 'border.primary',
										backgroundColor:
											hoverIndex === i + 1 && !drag.valid
												? 'error.bg'
												: hoverIndex === i + 1
													? 'bg.tertiary'
													: 'transparent',
										_hover: { backgroundColor: 'bg.hover' }
									})}
								>
									{#if hoverIndex === i + 1}
										<span
											class={css({
												fontFamily: 'mono',
												fontSize: 'sm',
												fontWeight: '500',
												textTransform: 'lowercase'
											})}>{drag.type ?? 'step'}</span
										>
									{/if}
								</div>
								{#if i < steps.length - 1}
									<ConnectionLine
										fromStepIndex={i}
										toStepIndex={i + 1}
										totalSteps={steps.length}
										highlighted={hoverIndex === i + 1}
									/>
								{/if}
							{/if}
						</div>
					{:else if i < steps.length - 1 || !drag.isReorder || drag.stepId !== step.id}
						<div
							class={css({
								display: 'flex',
								alignItems: 'center',
								justifyContent: 'center',
								paddingY: '2'
							})}
							aria-hidden="true"
						>
							<ConnectionLine fromStepIndex={i} toStepIndex={i + 1} totalSteps={steps.length} />
						</div>
					{/if}
				{/if}
			{/each}
			{#if steps.length > 0}
				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'center',
						paddingY: '2'
					})}
					aria-hidden="true"
				>
					<ConnectionLine
						fromStepIndex={steps.length - 1}
						toStepIndex={steps.length}
						totalSteps={steps.length + 1}
					/>
				</div>
			{:else}
				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'center',
						paddingY: '2'
					})}
					aria-hidden="true"
				>
					<ConnectionLine fromStepIndex={-1} toStepIndex={0} totalSteps={1} />
				</div>
			{/if}
			<OutputNode {analysisId} {datasourceId} {activeTab} />
		</div>
	{/if}
</div>

<style>
	.insert-zone.ready:hover :global(.connection-line) {
		color: var(--colors-accent-primary);
	}
</style>
