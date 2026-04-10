<script lang="ts">
	import type { PipelineStep } from '$lib/types/analysis';
	import { drag, type DropTarget } from '$lib/stores/drag.svelte';
	import InlineDataTable from '$lib/components/pipeline/InlineDataTable.svelte';
	import ChartPreview from '$lib/components/pipeline/ChartPreview.svelte';
	import { createQuery } from '@tanstack/svelte-query';
	import {
		previewStepData,
		getStepRowCount,
		downloadStep,
		type StepPreviewResponse
	} from '$lib/api/compute';
	import { applySteps } from '$lib/utils/pipeline';
	import { hashPipeline } from '$lib/utils/hash';
	import { GripVertical, Hash, RefreshCw, Copy, Trash2 } from 'lucide-svelte';
	import { analysisStore } from '$lib/stores/analysis.svelte';
	import { datasourceStore } from '$lib/stores/datasource.svelte';
	import { getStepTypeConfig, isChartStep } from '$lib/components/pipeline/utils';
	import {
		buildAnalysisPipelinePayload,
		buildDatasourceConfig
	} from '$lib/utils/analysis-pipeline';
	import { SvelteMap } from 'svelte/reactivity';
	import { css, cx, spinner, button } from '$lib/styles/panda';

	interface Props {
		step: PipelineStep;
		index: number;
		analysisId?: string;
		datasourceId?: string;
		allSteps?: PipelineStep[];
		onEdit: (id: string) => void;
		onDelete: (id: string) => void;
		onToggleApply: (id: string) => void;
		onTouchMove: (stepId: string, target: DropTarget) => void;
		readOnly?: boolean;
	}

	let {
		step,
		index: _index,
		analysisId,
		datasourceId,
		allSteps = [],
		onEdit,
		onDelete,
		onToggleApply,
		onTouchMove,
		readOnly = false
	}: Props = $props();

	const isChart = $derived(isChartStep(step.type));

	const chartHeight = $derived(
		isChart ? (step.config?.chart_height as string | undefined) : undefined
	);

	const nodeWidthClass = $derived.by(() => {
		return css({ width: '60%' });
	});

	const chartHeightPx = $derived.by(() => {
		if (chartHeight === 'small') return 260;
		if (chartHeight === 'large') return 520;
		if (chartHeight === 'xlarge') return 680;
		return 380;
	});

	// Derived values from declarative config
	const stepConfig = $derived(getStepTypeConfig(step.type));
	const Icon = $derived(stepConfig.icon);
	const label = $derived(stepConfig.label);
	const summary = $derived(stepConfig.summary(step.config as Record<string, unknown>));
	const isApplied = $derived(step.is_applied !== false);

	// Chart preview query (only for chart/plot steps) — run after apply
	const chartPipeline = $derived(applySteps(allSteps));
	const chartPipelineKey = $derived(hashPipeline(chartPipeline));
	const chartDatasourceConfig = $derived.by(() => {
		if (!isChart) return {};
		const config = buildDatasourceConfig({
			analysisId: analysisId ?? null,
			tab: analysisStore.activeTab ?? null,
			tabs: analysisStore.tabs,
			datasources: datasourceStore.datasources
		});
		if (config) return config;
		const active = analysisStore.activeTab;
		if (!active) return {};
		return active.datasource.config;
	});
	const analysisPipeline = $derived.by(() => {
		if (!analysisId) return null;
		return buildAnalysisPipelinePayload(
			analysisId,
			analysisStore.tabs,
			datasourceStore.datasources
		);
	});

	const chartQuery = createQuery(() => ({
		queryKey: [
			'chart-preview',
			analysisId,
			datasourceId,
			step.id,
			chartPipelineKey,
			JSON.stringify(chartDatasourceConfig)
		],
		queryFn: async (): Promise<StepPreviewResponse> => {
			const result = await previewStepData({
				analysis_pipeline: analysisPipeline!,
				tab_id: analysisStore.activeTab?.id ?? null,
				target_step_id: step.id,
				row_limit: 5000,
				page: 1,
				resource_config: analysisStore.resourceConfig
			});
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		staleTime: Infinity,
		gcTime: Infinity,
		refetchOnMount: false,
		retry: false,
		enabled:
			isChart &&
			isApplied &&
			!!datasourceId &&
			!!analysisId &&
			!!analysisPipeline &&
			((step.config?.x_column as string | undefined) ?? '') !== ''
	}));

	const rowCounts = new SvelteMap<string, number>();

	const rowCountLoads = new SvelteMap<string, boolean>();
	const rowCountErrors = new SvelteMap<string, string>();

	const rowCountPipeline = $derived(applySteps(allSteps));
	const rowCountPipelineKey = $derived(hashPipeline(rowCountPipeline));
	const rowCountDatasourceConfig = $derived.by(() => {
		const config = buildDatasourceConfig({
			analysisId: analysisId ?? null,
			tab: analysisStore.activeTab ?? null,
			tabs: analysisStore.tabs,
			datasources: datasourceStore.datasources
		});
		if (config) return config;
		const active = analysisStore.activeTab;
		if (!active) return {};
		return active.datasource.config;
	});
	const rowCountKey = $derived.by(() => {
		const configKey = JSON.stringify(rowCountDatasourceConfig ?? {});
		return `${analysisId ?? ''}:${datasourceId ?? ''}:${step.id}:${rowCountPipelineKey}:${configKey}`;
	});
	const rowCount = $derived(rowCounts.get(rowCountKey) ?? null);
	const isLoadingRowCount = $derived(rowCountLoads.get(rowCountKey) ?? false);
	const rowCountError = $derived(rowCountErrors.get(rowCountKey) ?? null);
	const rowCountLabel = $derived.by(() => {
		if (rowCount === null) return '';
		return `${rowCount.toLocaleString()} rows`;
	});

	async function calculateRowCount() {
		if (!analysisId || !analysisPipeline) return;
		if (isLoadingRowCount) return;
		rowCountLoads.set(rowCountKey, true);
		rowCountErrors.delete(rowCountKey);
		const result = await getStepRowCount({
			analysis_pipeline: analysisPipeline!,
			tab_id: analysisStore.activeTab?.id ?? null,
			target_step_id: step.id
		});
		rowCountLoads.set(rowCountKey, false);
		if (result.isErr()) {
			rowCountErrors.set(rowCountKey, result.error.message);
			return;
		}
		rowCounts.set(rowCountKey, result.value.row_count);
		rowCountErrors.delete(rowCountKey);
	}

	let copyFeedback = $state(false);
	let copyTimer = $state<number | null>(null);

	async function copyStepToClipboard() {
		const payload = JSON.stringify({
			type: step.type,
			config: step.config,
			is_applied: step.is_applied
		});
		await navigator.clipboard.writeText(payload).catch(() => {});
		copyFeedback = true;
		if (copyTimer !== null) window.clearTimeout(copyTimer);
		copyTimer = window.setTimeout(() => {
			copyFeedback = false;
			copyTimer = null;
		}, 1200);
	}

	$effect(() => {
		return () => {
			if (copyTimer !== null) window.clearTimeout(copyTimer);
		};
	});

	let dragging = $state(false);
	let clickConsumed = $state(false);
	let longPressTimer = $state<number | null>(null);
	let pointerStartX = $state<number | null>(null);
	let pointerStartY = $state<number | null>(null);

	const longPressDelay = 180;
	const dragThreshold = 8;

	// Is this node being dragged?
	let isDragging = $state(false);

	// Is another node being dragged (not this one)?
	const isOtherDragging = $derived(drag.active && drag.stepId !== step.id);

	function handleClick(event: MouseEvent) {
		if (!clickConsumed) return;
		event.preventDefault();
		event.stopPropagation();
		clickConsumed = false;
	}

	async function handleDownload() {
		if (!analysisId || !analysisPipeline) return;

		downloadStep({
			analysis_id: analysisId,
			target_step_id: step.id,
			analysis_pipeline: analysisPipeline,
			tab_id: analysisStore.activeTab?.id ?? null,
			format:
				(step.config?.format as 'csv' | 'parquet' | 'json' | 'ndjson' | 'excel' | 'duckdb') ??
				'csv',
			filename: (step.config?.filename as string) ?? 'download'
		});
	}

	function startDrag(event: PointerEvent) {
		if (readOnly) return;
		const target = event.currentTarget as HTMLElement | null;
		const handle = target?.closest('[data-drag-handle]');
		if (!handle) return;

		pointerStartX = event.clientX;
		pointerStartY = event.clientY;

		// For touch inputs, require long press to prevent accidental drags
		if (event.pointerType === 'touch') {
			longPressTimer = window.setTimeout(() => {
				initiateDrag(event);
			}, longPressDelay);
			return;
		}
		// For mouse/trackpad, start drag immediately
		initiateDrag(event);
	}

	function initiateDrag(event: PointerEvent) {
		dragging = true;
		clickConsumed = true;
		isDragging = true;
		if (event.cancelable) {
			event.preventDefault();
		}
		drag.startMove(step.id, step.type, event.pointerId, event.clientX, event.clientY, onTouchMove);
		if (event.currentTarget instanceof HTMLElement) {
			event.currentTarget.setPointerCapture(event.pointerId);
			drag.setCapturedElement(event.currentTarget, event.pointerId);
		}
	}

	function cancelLongPress() {
		if (longPressTimer !== null) window.clearTimeout(longPressTimer);
		longPressTimer = null;
		pointerStartX = null;
		pointerStartY = null;
	}

	function handlePointerMove(event: PointerEvent) {
		// If we haven't started dragging yet, check if pointer moved too much (cancel long press)
		if (pointerStartX !== null && pointerStartY !== null && !dragging) {
			const deltaX = Math.abs(event.clientX - pointerStartX);
			const deltaY = Math.abs(event.clientY - pointerStartY);
			const moved = deltaX > dragThreshold || deltaY > dragThreshold;
			if (moved) {
				cancelLongPress();
				return;
			}
		}

		// If we're dragging, update pointer position
		if (!dragging) return;
		drag.setPointer(event.clientX, event.clientY);
		event.preventDefault();
	}

	function finishDrag(): void {
		if (dragging && drag.active) {
			drag.commit();
		}
		const wasDragging = dragging;
		dragging = false;
		clickConsumed = wasDragging;
		isDragging = false;
		cancelLongPress();
	}
</script>

<div
	class={cx(
		'step-node',
		nodeWidthClass,
		isDragging &&
			css({
				opacity: '0.4',
				filter: 'grayscale(1)'
			}),
		css({
			position: 'relative',
			contentVisibility: 'auto',
			containIntrinsicSize: isChart || step.type === 'view' ? 'auto 600px' : 'auto 200px',
			...(step.type === 'view' || isChart ? { width: '85%', minWidth: 'listLg' } : {})
		})
	)}
	data-step-id={step.id}
	data-step-type={step.type}
>
	<div
		class={cx(
			'step-content',
			css({
				borderWidth: '1',
				backgroundColor: 'bg.primary'
			}),
			isOtherDragging &&
				css({
					borderStyle: 'dashed',
					opacity: '0.7',
					transform: 'scale(0.98)'
				})
		)}
		role="listitem"
	>
		<div
			class={css({
				display: 'flex',
				alignItems: 'center',
				gap: '2',
				paddingX: '4',
				paddingY: '3',
				borderBottomWidth: '1'
			})}
		>
			<button
				class={cx(
					'drag-handle',
					css({
						display: 'flex',
						flexShrink: '0',
						cursor: readOnly ? 'not-allowed' : 'grab',
						alignItems: 'center',
						justifyContent: 'center',
						border: 'none',
						backgroundColor: 'transparent',
						padding: '0.5',
						opacity: '0.3',
						userSelect: 'none',
						color: 'fg.muted',
						_hover: { opacity: '1', backgroundColor: 'bg.hover' },
						_active: { cursor: readOnly ? 'not-allowed' : 'grabbing' },
						...(dragging
							? {
									WebkitUserSelect: 'none',
									WebkitTouchCallout: 'none',
									touchAction: 'none'
								}
							: {})
					})
				)}
				title="Drag to reorder"
				type="button"
				onpointerdown={startDrag}
				onpointermove={handlePointerMove}
				onpointerup={finishDrag}
				onpointercancel={finishDrag}
				onclick={handleClick}
				data-drag-handle="true"
				disabled={readOnly}
			>
				<GripVertical size={14} />
			</button>

			<Icon size={13} class={css({ flexShrink: '0', color: 'fg.muted' })} />
			<span
				class={css({
					flex: '1',
					fontSize: 'xs',
					fontWeight: 'semibold',
					textTransform: 'uppercase',
					letterSpacing: 'wide'
				})}
			>
				{label}
			</span>
			<button
				class={css({
					flexShrink: '0',
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'center',
					cursor: 'pointer',
					border: 'none',
					backgroundColor: 'transparent',
					padding: '0.5',
					color: copyFeedback ? 'fg.success' : 'fg.faint',
					_hover: { color: 'fg.primary', backgroundColor: 'bg.hover' }
				})}
				onclick={copyStepToClipboard}
				type="button"
				title="Copy step to clipboard"
			>
				<Copy size={11} />
			</button>
			<button
				class={css({
					flexShrink: '0',
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'center',
					cursor: 'pointer',
					border: 'none',
					backgroundColor: 'transparent',
					padding: '0.5',
					color: 'fg.faint',
					_hover: { color: 'fg.error', backgroundColor: 'bg.hover' },
					_disabled: { opacity: '0.4', cursor: 'not-allowed' }
				})}
				onclick={() => onDelete(step.id)}
				type="button"
				title="Delete step"
				data-action="delete"
				disabled={readOnly}
			>
				<Trash2 size={11} />
			</button>
		</div>

		<div class={css({ paddingX: '4', paddingY: '3' })}>
			<div
				class={cx(
					'step-summary',
					css({
						paddingX: '3',
						paddingY: '2',
						fontSize: 'xs2',
						backgroundColor: 'bg.secondary',
						color: 'fg.tertiary',
						lineHeight: 'relaxed',
						...(!isApplied
							? {
									backgroundColor: 'bg.secondary',
									color: 'fg.muted',
									border: '1px dashed'
								}
							: {})
					})
				)}
			>
				{summary}
			</div>
		</div>

		<div class={css({ borderTopWidth: '1', display: 'flex', gap: '0' })}>
			<button
				class={cx(
					'action-btn',
					css({
						flex: '1',
						cursor: 'pointer',
						border: 'none',
						backgroundColor: 'transparent',
						paddingY: '2.5',
						fontWeight: 'medium',
						textTransform: 'uppercase',
						letterSpacing: 'widest',
						fontSize: '3xs',
						color: 'fg.muted',
						_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' },
						...(!isApplied
							? {
									borderStyle: 'dashed',
									color: 'fg.muted',
									_hover: {
										backgroundColor: 'bg.tertiary',
										color: 'fg.secondary'
									}
								}
							: {})
					})
				)}
				onclick={() => onToggleApply(step.id)}
				type="button"
				title={isApplied ? 'Disable step' : 'Enable step'}
				data-action="toggle"
				disabled={readOnly}
			>
				{isApplied ? 'disable' : 'enable'}
			</button>
			<div class={css({ width: 'px', backgroundColor: 'bg.muted', flexShrink: '0' })}></div>
			<button
				class={cx(
					'action-btn',
					css({
						flex: '1',
						cursor: 'pointer',
						border: 'none',
						backgroundColor: 'transparent',
						paddingY: '2.5',
						fontSize: '3xs',
						fontWeight: 'medium',
						textTransform: 'uppercase',
						letterSpacing: 'widest',
						color: 'fg.muted',
						_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' }
					})
				)}
				onclick={() => onEdit(step.id)}
				type="button"
				data-action="edit"
				disabled={readOnly}
			>
				edit
			</button>
		</div>

		{#if step.type === 'view' && datasourceId && analysisId}
			<div class={css({ borderTopWidth: '1' })}>
				<InlineDataTable
					{analysisId}
					{datasourceId}
					pipeline={allSteps}
					stepId={step.id}
					rowLimit={typeof step.config?.rowLimit === 'number' ? step.config.rowLimit : 100}
				/>
			</div>
		{/if}

		{#if step.type === 'download' && datasourceId && analysisId}
			<div class={css({ borderTopWidth: '1', padding: '3' })}>
				<button
					class={cx(button({ variant: 'primary' }), css({ width: '100%' }))}
					onclick={() => handleDownload()}
					disabled={!isApplied || !analysisPipeline}
				>
					Download File
				</button>
			</div>
		{/if}

		{#if isChart && datasourceId && analysisId}
			<div class={css({ borderTopWidth: '1' })}>
				{#if !isApplied}
					<div
						class={css({
							display: 'flex',
							alignItems: 'center',
							justifyContent: 'center',
							fontSize: 'xs2',
							color: 'fg.muted',
							border: '1px dashed',
							backgroundColor: 'bg.primary'
						})}
						style:height="{chartHeightPx}px"
					>
						<Icon size={14} class={css({ marginRight: '2' })} />
						{#if ((step.config?.x_column as string | undefined) ?? '') === ''}
							<span>Configure chart to preview</span>
						{:else}
							<span>Apply to preview</span>
						{/if}
					</div>
				{:else if chartQuery.isFetching}
					<div
						class={css({
							display: 'flex',
							alignItems: 'center',
							justifyContent: 'center',
							gap: '2',
							paddingY: '5',
							fontSize: 'xs2',
							color: 'fg.muted'
						})}
					>
						<span class={spinner({ size: 'sm' })}></span>
						Loading chart...
					</div>
				{:else if chartQuery.error}
					<div
						class={css({
							borderTopWidth: '1',
							borderTopColor: 'border.error',
							backgroundColor: 'bg.error',
							padding: '3',
							fontSize: 'xs',
							color: 'fg.error'
						})}
					>
						{chartQuery.error.message}
					</div>
				{:else if chartQuery.data}
					<ChartPreview
						data={chartQuery.data.data}
						chartType={(step.config.chart_type as
							| 'bar'
							| 'horizontal_bar'
							| 'area'
							| 'heatgrid'
							| 'line'
							| 'pie'
							| 'histogram'
							| 'scatter'
							| 'boxplot') ?? 'bar'}
						config={step.config}
						metadata={chartQuery.data.metadata}
						height={chartHeightPx}
					/>
				{/if}
			</div>
		{/if}

		<div
			class={css({
				borderTopWidth: '1',
				display: 'flex',
				alignItems: 'center',
				paddingX: '4',
				paddingY: '2.5'
			})}
		>
			{#if rowCount !== null}
				{#key `${rowCountKey}:${rowCount}`}
					<span
						class={css({
							display: 'flex',
							alignItems: 'center',
							gap: '1',
							fontSize: '2xs',
							color: 'fg.faint'
						})}
						data-testid="step-row-count"
					>
						<Hash size={9} />
						{rowCountLabel}
					</span>
				{/key}
			{:else}
				<button
					class={css({
						display: 'flex',
						cursor: 'pointer',
						alignItems: 'center',
						gap: '1',
						borderWidth: '1',
						backgroundColor: 'transparent',
						color: 'fg.muted',
						paddingX: '2',
						paddingY: '0.5',
						fontSize: '3xs',
						_hover: { backgroundColor: 'bg.hover', color: 'fg.primary' },
						_disabled: { cursor: 'not-allowed', opacity: '0.7' }
					})}
					onclick={calculateRowCount}
					disabled={isLoadingRowCount || !analysisPipeline}
					type="button"
					aria-label="Calculate row count"
					data-action="count-rows"
					data-testid="step-row-count-button"
				>
					{#if isLoadingRowCount}
						<RefreshCw size={9} class={css({ animation: 'spin 1s linear infinite' })} />
						<span>counting...</span>
					{:else}
						<Hash size={9} />
						<span>count rows</span>
					{/if}
				</button>
			{/if}
		</div>
		{#if rowCountError}
			<div
				class={css({
					borderTopWidth: '1',
					borderTopColor: 'border.error',
					backgroundColor: 'bg.error',
					paddingX: '4',
					paddingY: '2',
					fontSize: 'xs',
					color: 'fg.error'
				})}
				data-testid="step-row-count-error"
			>
				{rowCountError}
			</div>
		{/if}
	</div>
</div>
