<script lang="ts">
	import type { PipelineStep, AnalysisTab } from '$lib/types/analysis';
	import type { DataSource } from '$lib/types/datasource';
	import type { BuildStreamStore } from '$lib/stores/build-stream.svelte';
	import { drag, type DropTarget } from '$lib/stores/drag.svelte';
	import StepNode from './StepNode.svelte';
	import OutputNode from './OutputNode.svelte';
	import ConnectionLine from './ConnectionLine.svelte';
	import DatasourceNode from './DatasourceNode.svelte';
	import { css } from '$lib/styles/panda';
	import { ClipboardPaste, Plus, Eye, ArrowDown } from 'lucide-svelte';
	import { stepTypes, isChartStep } from './utils';

	export interface ClipboardStep {
		type: string;
		config: Record<string, unknown>;
		is_applied?: boolean;
	}

	interface Props {
		steps: PipelineStep[];
		buildStore: BuildStreamStore;
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
		onPasteStep: (payload: ClipboardStep, target: DropTarget) => void;
		onMoveStep: (stepId: string, target: DropTarget) => void;
		onChangeDatasource?: () => void;
		onRenameTab?: (name: string) => void;
		onDuplicateTab?: () => void;
		readOnly?: boolean;
	}

	let {
		steps,
		buildStore,
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
		onPasteStep,
		onMoveStep,
		onChangeDatasource: _onChangeDatasource,
		onRenameTab: _onRenameTab,
		onDuplicateTab: _onDuplicateTab,
		readOnly = false
	}: Props = $props();

	const canDrop = $derived(!readOnly && drag.active);
	const hoverIndex = $derived(drag.target?.index ?? null);
	const activeTabId = $derived(activeTab?.id ?? null);

	let lastTabId = $state<string | null>(null);
	let pasteError = $state<string | null>(null);
	let canvasEl = $state<HTMLElement | null>(null);
	let outputEl = $state<HTMLElement | null>(null);
	let outputVisible = $state(true);

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

	// Timer: clear paste error after 3s — $derived can't schedule timeouts
	$effect(() => {
		if (!pasteError) return;
		const timer = window.setTimeout(() => (pasteError = null), 3000);
		return () => window.clearTimeout(timer);
	});

	function observeOutput(node: HTMLElement): () => void {
		const observer = new IntersectionObserver(
			(entries) => {
				outputVisible = entries[0]?.isIntersecting ?? true;
			},
			{ threshold: 0.1 }
		);
		observer.observe(node);
		return () => observer.disconnect();
	}

	function scrollToOutput() {
		outputEl?.scrollIntoView({ behavior: 'smooth', block: 'end' });
	}

	function buildTarget(index: number): DropTarget {
		return {
			index,
			parentId: index === 0 ? null : (steps[index - 1]?.id ?? null),
			nextId: steps[index]?.id ?? null
		};
	}

	function isClipboardStep(data: unknown): data is ClipboardStep {
		if (typeof data !== 'object' || data === null) return false;
		const obj = data as Record<string, unknown>;
		if (typeof obj.type !== 'string') return false;
		if (typeof obj.config !== 'object' || obj.config === null) return false;
		return true;
	}

	async function handlePaste(index: number) {
		if (readOnly) return;
		try {
			const text = await navigator.clipboard.readText();
			const parsed: unknown = JSON.parse(text);
			if (!isClipboardStep(parsed)) {
				pasteError = 'Clipboard does not contain a valid step';
				return;
			}
			if (!(parsed.type in stepTypes) && !isChartStep(parsed.type)) {
				pasteError = `Unknown step type: ${parsed.type}`;
				return;
			}
			const target = buildTarget(index);
			onPasteStep(parsed, target);
		} catch {
			pasteError = 'Could not read clipboard';
		}
	}

	function handleInsertView(index: number) {
		if (readOnly) return;
		const target = buildTarget(index);
		onInsertStep('view', target);
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

		if (drag.type && isChartStep(drag.type)) {
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
		if (readOnly || !drag.active) return;
		event.preventDefault();
		const target = buildTarget(index);
		const valid = isValidTarget(index);
		drag.setTarget(target, valid);
	}

	function handleDragOver(event: DragEvent) {
		if (!readOnly && drag.active) {
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
		if (readOnly || !drag.active) return;

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

	// Lifecycle: register synchronous target resolver so commit() can
	// resolve the drop target even if the reactive $effect above hasn't run yet.
	$effect(() => {
		drag.setTargetResolver((x: number, y: number) => {
			const target = resolveTargetFromPoint(x, y);
			if (!target) return null;
			return { target, valid: isValidTarget(target.index) };
		});
		return () => drag.setTargetResolver(null);
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

	const insertControls = [
		'insert-controls-group',
		css({
			display: 'flex',
			alignItems: 'center',
			justifyContent: 'center',
			gap: '0.5',
			position: 'absolute',
			inset: '0',
			opacity: '0',
			transitionProperty: 'opacity',
			transitionDuration: '150ms',
			zIndex: '2'
		})
	];
</script>

<div
	class={css({
		flex: '1',
		width: '100%',
		display: 'flex',
		flexDirection: 'column',
		position: 'relative',
		minHeight: 'panel',
		overflow: 'hidden'
	})}
>
	<div
		bind:this={canvasEl}
		class={[
			'pipeline-canvas',
			css({
				flex: '1',
				overflowY: 'auto',
				padding: '8',
				backgroundColor: 'bg.secondary'
			})
		]}
	>
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
				onDuplicateTab={_onDuplicateTab}
				{readOnly}
			/>
			{#if shouldShowInsert(0)}
				<div
					class={[
						'insert-zone',
						css({
							display: 'flex',
							width: '100%',
							cursor: canDrop ? 'pointer' : 'default',
							flexDirection: 'column',
							alignItems: 'center',
							paddingY: '0'
						})
					]}
					class:ready={canDrop}
					role="listitem"
					data-hook="insert-zone"
					data-index="0"
					ondragenter={(e) => handleDragEnter(e, 0)}
					ondragover={handleDragOver}
					ondragleave={handleDragLeave}
					ondrop={(e) => handleDrop(e, 0)}
				>
					{#if canDrop}
						<ConnectionLine
							fromStepIndex={-1}
							toStepIndex={0}
							totalSteps={steps.length + 1}
							highlighted={hoverIndex === 0}
						/>
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
										? 'bg.error'
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
										fontWeight: 'medium',
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
					{:else}
						<div
							class={css({
								position: 'relative',
								display: 'flex',
								flexDirection: 'column',
								alignItems: 'center',
								justifyContent: 'center'
							})}
						>
							<ConnectionLine
								fromStepIndex={-1}
								toStepIndex={0}
								totalSteps={steps.length + 1}
								highlighted={false}
								arrow={false}
							/>
							{#if steps.length > 0}
								<ConnectionLine
									fromStepIndex={-1}
									toStepIndex={0}
									totalSteps={steps.length + 1}
									highlighted={false}
								/>
							{/if}
							{#if !readOnly}
								<div class={insertControls}>
									<button
										class={css({
											display: 'inline-flex',
											alignItems: 'center',
											justifyContent: 'center',
											padding: '0.5',
											borderRadius: 'xs',
											backgroundColor: 'transparent',
											border: 'none',
											cursor: 'pointer',
											transitionProperty: 'color',
											transitionDuration: '150ms',
											_hover: { color: 'fg.primary' }
										})}
										title="Insert view"
										onclick={() => handleInsertView(0)}
									>
										<Eye size={14} />
									</button>
									<div
										class={css({
											display: 'inline-flex',
											alignItems: 'center',
											justifyContent: 'center',
											padding: '0.5',
											color: 'fg.faint'
										})}
										aria-hidden="true"
									>
										<Plus size={14} />
									</div>
									<button
										class={css({
											display: 'inline-flex',
											alignItems: 'center',
											justifyContent: 'center',
											padding: '0.5',
											borderRadius: 'xs',
											backgroundColor: 'transparent',
											border: 'none',
											cursor: 'pointer',
											transitionProperty: 'color',
											transitionDuration: '150ms',
											_hover: { color: 'fg.primary' }
										})}
										title="Paste step"
										onclick={() => handlePaste(0)}
									>
										<ClipboardPaste size={14} />
									</button>
								</div>
							{/if}
						</div>
					{/if}
				</div>
			{:else if steps.length > 0}
				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'center',
						paddingY: '0'
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
					{readOnly}
				/>
				{#if shouldShowInsert(i + 1)}
					<div
						class={[
							'insert-zone',
							css({
								display: 'flex',
								width: '100%',
								cursor: canDrop ? 'pointer' : 'default',
								flexDirection: 'column',
								alignItems: 'center',
								paddingY: '0'
							})
						]}
						class:ready={canDrop}
						role="listitem"
						data-hook="insert-zone"
						data-index={i + 1}
						ondragenter={(e) => handleDragEnter(e, i + 1)}
						ondragover={handleDragOver}
						ondragleave={handleDragLeave}
						ondrop={(e) => handleDrop(e, i + 1)}
					>
						{#if canDrop}
							{#if i < steps.length - 1 || !drag.isReorder || drag.stepId !== step.id}
								<ConnectionLine
									fromStepIndex={i}
									toStepIndex={i + 1}
									totalSteps={steps.length}
									highlighted={hoverIndex === i + 1}
								/>
							{/if}
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
											? 'bg.error'
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
											fontWeight: 'medium',
											textTransform: 'lowercase'
										})}>{drag.type ?? 'step'}</span
									>
								{/if}
							</div>
							<ConnectionLine
								fromStepIndex={i}
								toStepIndex={i + 1}
								totalSteps={steps.length}
								highlighted={hoverIndex === i + 1}
							/>
						{:else}
							<div
								class={css({
									position: 'relative',
									display: 'flex',
									flexDirection: 'column',
									alignItems: 'center',
									justifyContent: 'center'
								})}
							>
								<ConnectionLine
									fromStepIndex={i}
									toStepIndex={i + 1}
									totalSteps={steps.length}
									highlighted={false}
									arrow={false}
								/>
								<ConnectionLine
									fromStepIndex={i}
									toStepIndex={i + 1}
									totalSteps={steps.length}
									highlighted={false}
								/>
								{#if !readOnly}
									<div class={insertControls}>
										<button
											class={css({
												display: 'inline-flex',
												alignItems: 'center',
												justifyContent: 'center',
												padding: '0.5',
												borderRadius: 'xs',
												backgroundColor: 'transparent',
												border: 'none',
												cursor: 'pointer',
												transitionProperty: 'color',
												transitionDuration: '150ms',
												_hover: { color: 'fg.primary' }
											})}
											title="Insert view"
											onclick={() => handleInsertView(i + 1)}
										>
											<Eye size={14} />
										</button>
										<div
											class={css({
												display: 'inline-flex',
												alignItems: 'center',
												justifyContent: 'center',
												padding: '0.5',
												color: 'fg.faint'
											})}
											aria-hidden="true"
										>
											<Plus size={14} />
										</div>
										<button
											class={css({
												display: 'inline-flex',
												alignItems: 'center',
												justifyContent: 'center',
												padding: '0.5',
												borderRadius: 'xs',
												backgroundColor: 'transparent',
												border: 'none',
												cursor: 'pointer',
												transitionProperty: 'color',
												transitionDuration: '150ms',
												_hover: { color: 'fg.primary' }
											})}
											title="Paste step"
											onclick={() => handlePaste(i + 1)}
										>
											<ClipboardPaste size={14} />
										</button>
									</div>
								{/if}
							</div>
						{/if}
					</div>
				{:else if i < steps.length - 1 || !drag.isReorder || drag.stepId !== step.id}
					<div
						class={css({
							display: 'flex',
							alignItems: 'center',
							justifyContent: 'center',
							paddingY: '0'
						})}
						aria-hidden="true"
					>
						<ConnectionLine fromStepIndex={i} toStepIndex={i + 1} totalSteps={steps.length} />
					</div>
				{/if}
			{/each}
			{#if steps.length === 0}
				<div
					class={css({
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'center',
						paddingY: '0'
					})}
					aria-hidden="true"
				>
					<ConnectionLine fromStepIndex={-1} toStepIndex={0} totalSteps={1} />
				</div>
			{/if}
			<div
				bind:this={outputEl}
				class={css({ width: '100%', display: 'flex', justifyContent: 'center' })}
				{@attach observeOutput}
			>
				<OutputNode {buildStore} {analysisId} {datasourceId} {activeTab} {readOnly} />
			</div>
		</div>
		{#if pasteError}
			<div
				class={css({
					position: 'fixed',
					bottom: '4',
					left: '50%',
					transform: 'translateX(-50%)',
					backgroundColor: 'bg.error',
					borderWidth: '1',
					borderColor: 'border.error',
					color: 'fg.error',
					paddingX: '4',
					paddingY: '2',
					fontSize: 'sm',
					zIndex: 'toast'
				})}
			>
				{pasteError}
			</div>
		{/if}
	</div>
	{#if !outputVisible}
		<button
			onclick={scrollToOutput}
			title="Scroll to output"
			class={css({
				position: 'absolute',
				bottom: '0',
				right: '0',
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'center',
				padding: '0',
				width: '10',
				height: '10',
				borderRadius: 'md',
				borderWidth: '1',
				borderColor: 'border.primary',
				cursor: 'pointer',
				boxShadow: 'md',
				transitionProperty: 'color, background-color, border-color',
				transitionDuration: '150ms',
				_hover: {
					backgroundColor: 'bg.hover',
					color: 'fg.primary'
				}
			})}
		>
			<ArrowDown size={18} />
		</button>
	{/if}
</div>

<style>
	.insert-zone.ready:hover :global(.connection-line) {
		color: var(--colors-accent-primary);
	}

	.insert-zone:hover :global(.insert-controls-group) {
		opacity: 1;
	}

	/* When hovering, hide the chain line — only insert prompts remain */
	.insert-zone:not(.ready):hover :global(.connection-line) {
		opacity: 0;
	}
</style>
