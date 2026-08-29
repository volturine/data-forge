<script lang="ts">
	import { Chart } from '@tanstack/charts/svelte';
	import { downloadChartImage } from '@tanstack/charts/export';
	import { ChevronLeft, ChevronRight } from '@lucide/svelte';
	import { css } from '$lib/styles/panda';
	import { downloadBlob } from '$lib/api/compute';
	import { SvelteSet } from 'svelte/reactivity';
	import { buildChart, type ChartHandlers, type ChartInteraction } from '$lib/charts/definition';
	import { readString, type ChartType as ConfigChartType } from '$lib/charts/format';
	import { chartCsv } from '$lib/charts/csv';

	interface Props {
		data: Record<string, unknown>[];
		chartType: ConfigChartType;
		config: Record<string, unknown>;
		metadata?: Record<string, unknown> | null;
		height?: number;
	}

	const { data, chartType, config, metadata, height = 300 }: Props = $props();

	const TITLE_HEIGHT = 28;

	/* ── interaction state ── */
	const hiddenSeries = new SvelteSet<string>();
	let legendCollapsed = $state(false);
	let selectedKey = $state<string | null>(null);
	let zoomWindow = $state<[number, number] | null>(null);
	let brushRange = $state<[number, number] | null>(null);
	let exportContainer: HTMLElement | null = $state(null);

	const handlers: ChartHandlers = {
		onZoomWindow(value) {
			zoomWindow = value;
		},
		onSelectedKey(value) {
			selectedKey = value;
		},
		onBrushRange(value) {
			brushRange = value;
		}
	};

	const legendPosition = $derived((readString(config, 'legend_position') || 'right') as string);
	const titleText = $derived(readString(config, 'title').trim());
	const selectEnabled = $derived(Boolean(config.selection_enabled));
	const zoomEnabled = $derived(Boolean(config.pan_zoom_enabled));
	const areaSelectEnabled = $derived(Boolean(config.area_selection_enabled));

	function visibleSeries(): ReadonlySet<string> {
		if (hiddenSeries.size === 0) return new Set<string>();
		return new Set(lastSeriesLabels.filter((label) => !hiddenSeries.has(label)));
	}

	let lastSeriesLabels: string[] = [];

	const built = $derived.by(() => {
		const interaction: ChartInteraction = {
			visibleSeries: visibleSeries(),
			selectedKey,
			zoomWindow,
			brushRange
		};
		const result = buildChart({ data, chartType, config, metadata, interaction, handlers });
		lastSeriesLabels = result.seriesLabels;
		return result;
	});

	const zoomActive = $derived.by(() => {
		const extent = built.zoomExtent;
		if (!extent || !zoomEnabled || !zoomWindow) return false;
		return zoomWindow[0] !== extent[0] || zoomWindow[1] !== extent[1];
	});

	function resetZoom() {
		zoomWindow = null;
	}

	function toggleSeries(label: string) {
		if (hiddenSeries.has(label)) hiddenSeries.delete(label);
		else hiddenSeries.add(label);
	}

	function isolateSeries(label: string) {
		hiddenSeries.clear();
		for (const item of built.seriesLabels) {
			if (item !== label) hiddenSeries.add(item);
		}
	}

	function onLegendClick(label: string, event: MouseEvent | KeyboardEvent) {
		if (event.metaKey || event.ctrlKey) {
			isolateSeries(label);
			return;
		}
		toggleSeries(label);
	}

	function isSeriesVisible(label: string): boolean {
		return !hiddenSeries.has(label);
	}

	function legendLabels(): string[] {
		return built.seriesLabels;
	}

	/* ── export ── */
	function onChartRender(context: { container: HTMLElement }): void {
		if (!exportContainer) exportContainer = context.container;
	}

	async function exportChartPng() {
		if (!exportContainer) return;
		const background = getComputedStyle(exportContainer).backgroundColor || '#ffffff';
		await downloadChartImage(exportContainer, 'chart.png', {
			scale: window.devicePixelRatio || 1,
			background
		});
	}

	function exportChartCsv() {
		const blob = new Blob([chartCsv(data, chartType, config, metadata ?? null)], {
			type: 'text/csv;charset=utf-8'
		});
		downloadBlob(blob, 'chart.csv');
	}

	function chartAriaLabel(): string {
		const title = readString(config, 'title').trim();
		if (title) return title;
		return `${chartType.replace('_', ' ')} chart`;
	}

	/* ── reset state that is no longer applicable ── */
	$effect(() => {
		if (!selectEnabled && selectedKey !== null) selectedKey = null;
		if (!zoomEnabled && zoomWindow !== null) zoomWindow = null;
		if (!areaSelectEnabled && brushRange !== null) brushRange = null;
	});

	/* ── legend styles ── */
	const legendTopCss = $derived(
		legendCollapsed
			? css({
					display: 'flex',
					flexWrap: 'wrap',
					alignItems: 'center',
					rowGap: '1',
					columnGap: '2',
					background: 'transparent',
					border: 'none',
					justifyContent: 'flex-end'
				})
			: css({
					display: 'flex',
					flexWrap: 'wrap',
					alignItems: 'center',
					rowGap: '1',
					columnGap: '2',
					backgroundColor: 'bg.secondary',
					borderBottomWidth: '1'
				})
	);

	const legendBottomFullCss = $derived(
		legendCollapsed
			? css({
					display: 'flex',
					flexWrap: 'wrap',
					alignItems: 'center',
					rowGap: '1',
					columnGap: '2',
					background: 'transparent',
					border: 'none',
					justifyContent: 'flex-start'
				})
			: css({
					display: 'flex',
					flexWrap: 'wrap',
					alignItems: 'center',
					rowGap: '1',
					columnGap: '2',
					backgroundColor: 'bg.secondary',
					borderTopWidth: '1',
					borderBottom: 'none'
				})
	);

	const sidePanelCss = $derived(
		legendPosition === 'right'
			? css({
					position: 'absolute',
					top: '7',
					right: '6',
					maxHeight: 'calc(100% - 44px)',
					display: 'flex',
					flexDirection: 'row',
					alignItems: 'flex-start',
					zIndex: '5'
				})
			: css({
					position: 'absolute',
					top: '7',
					left: '16',
					maxHeight: 'calc(100% - 44px)',
					display: 'flex',
					flexDirection: 'row',
					alignItems: 'flex-start',
					zIndex: '5'
				})
	);

	const sideTabCss = $derived.by(() => {
		if (legendPosition === 'right') {
			return legendCollapsed
				? css({
						flexShrink: '0',
						alignSelf: 'center',
						width: 'icon',
						height: 'rowXl',
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'center',
						cursor: 'pointer',
						background: 'color-mix(in srgb, {colors.bg.secondary} 95%, transparent)',
						borderWidth: '1',
						borderRadius: 'sm2',
						color: 'fg.muted',
						transition: 'background-color 120ms ease, color 120ms ease',
						_hover: { background: 'bg.tertiary', color: 'fg.primary' },
						'& svg': { stroke: 'currentColor' }
					})
				: css({
						flexShrink: '0',
						alignSelf: 'center',
						width: 'icon',
						height: 'rowXl',
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'center',
						cursor: 'pointer',
						background: 'color-mix(in srgb, {colors.bg.secondary} 95%, transparent)',
						borderWidth: '1',
						borderTopLeftRadius: 'sm2',
						borderBottomLeftRadius: 'sm2',
						borderRightWidth: '0',
						color: 'fg.muted',
						transition: 'background-color 120ms ease, color 120ms ease',
						_hover: { background: 'bg.tertiary', color: 'fg.primary' },
						'& svg': { stroke: 'currentColor' }
					});
		}
		return legendCollapsed
			? css({
					flexShrink: '0',
					alignSelf: 'center',
					width: 'icon',
					height: 'rowXl',
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'center',
					cursor: 'pointer',
					background: 'color-mix(in srgb, {colors.bg.secondary} 95%, transparent)',
					borderWidth: '1',
					borderRadius: 'sm2',
					color: 'fg.muted',
					transition: 'background-color 120ms ease, color 120ms ease',
					_hover: { background: 'bg.tertiary', color: 'fg.primary' },
					'& svg': { stroke: 'currentColor' }
				})
			: css({
					flexShrink: '0',
					alignSelf: 'center',
					width: 'icon',
					height: 'rowXl',
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'center',
					cursor: 'pointer',
					background: 'color-mix(in srgb, {colors.bg.secondary} 95%, transparent)',
					borderWidth: '1',
					borderTopRightRadius: 'sm2',
					borderBottomRightRadius: 'sm2',
					borderLeftWidth: '0',
					color: 'fg.muted',
					transition: 'background-color 120ms ease, color 120ms ease',
					_hover: { background: 'bg.tertiary', color: 'fg.primary' },
					'& svg': { stroke: 'currentColor' }
				});
	});

	const sideItemsCss = $derived(
		legendPosition === 'right'
			? css({
					display: 'flex',
					flexDirection: 'column',
					gap: 'px',
					paddingX: '1.5',
					paddingTop: '1.5',
					paddingBottom: '2',
					maxHeight: 'calc(100vh - 200px)',
					overflowY: 'auto',
					backgroundColor: 'color-mix(in srgb, {colors.bg.secondary} 95%, transparent)',
					borderWidth: '1',
					borderTopRightRadius: 'md2',
					borderBottomRightRadius: 'md2'
				})
			: css({
					display: 'flex',
					flexDirection: 'column',
					gap: 'px',
					paddingX: '1.5',
					paddingTop: '1.5',
					paddingBottom: '2',
					maxHeight: 'calc(100vh - 200px)',
					overflowY: 'auto',
					backgroundColor: 'color-mix(in srgb, {colors.bg.secondary} 95%, transparent)',
					borderWidth: '1',
					borderTopLeftRadius: 'md2',
					borderBottomLeftRadius: 'md2'
				})
	);

	const toolbarButtonCss = css({
		borderWidth: '1',
		backgroundColor: 'transparent',
		color: 'fg.secondary',
		borderColor: 'transparent',
		fontSize: 'xs',
		paddingX: '2',
		paddingY: '1',
		'&:hover:not(:disabled)': { backgroundColor: 'bg.hover', color: 'fg.primary' }
	});

	const legendItemCss = css({
		display: 'flex',
		alignItems: 'center',
		gap: '1',
		background: 'none',
		border: 'none',
		paddingY: '0.5',
		paddingX: '1',
		cursor: 'pointer',
		fontSize: '2xs',
		fontFamily: 'mono',
		color: 'fg.muted',
		transition: 'opacity 120ms ease',
		whiteSpace: 'nowrap',
		_hover: { color: 'fg.primary', backgroundColor: 'bg.tertiary' }
	});

	const legendDotCss = css({ width: 'dot', height: 'dot', borderRadius: 'xxs', flexShrink: '0' });

	const legendCollapseHandleCss = css({
		flexShrink: '0',
		alignSelf: 'stretch',
		width: 'bar',
		borderRadius: 'xs',
		marginLeft: 'px',
		cursor: 'pointer',
		opacity: '0',
		backgroundColor: 'bg.indicator',
		transition: 'opacity 150ms ease',
		'[data-legend-group]:hover &': { opacity: '0.15' },
		_hover: { opacity: '0.5' }
	});

	const legendPillCss = css({
		display: 'flex',
		alignItems: 'center',
		gap: 'px',
		paddingY: '1',
		paddingX: '2',
		borderWidth: '1',
		borderRadius: 'pill',
		cursor: 'pointer',
		transition: 'background 120ms ease, border-color 120ms ease',
		_hover: { background: 'bg.secondary' }
	});

	const legendPillDotCss = css({
		width: 'barTall',
		height: 'barTall',
		borderRadius: '50%',
		flexShrink: '0',
		transition: 'opacity 120ms ease'
	});

	const chartTitleCss = css({
		textAlign: 'center',
		fontSize: '12px',
		fontFamily: 'mono',
		color: 'fg.primary',
		paddingY: '1'
	});

	const piePaneLabelCss = css({
		textAlign: 'center',
		fontSize: '10px',
		fontFamily: 'mono',
		color: 'fg.muted'
	});
</script>

<div
	class={css({ width: '100%', backgroundColor: 'bg.primary', padding: '3' })}
	data-testid="chart-preview"
>
	{#if built.seriesLabels.length > 0 && legendPosition === 'top'}
		<div class={legendTopCss} data-legend-group>
			{#if legendCollapsed}
				<button
					type="button"
					class={legendPillCss}
					onclick={() => (legendCollapsed = false)}
					title="Show legend"
				>
					{#each legendLabels().slice(0, 12) as label (label)}
						<span
							class={[legendPillDotCss, !isSeriesVisible(label) && css({ opacity: '0.3' })]}
							style:background={built.colorOf(label)}
						></span>
					{/each}
				</button>
			{:else}
				{#each legendLabels() as label (label)}
					<button
						type="button"
						class={[legendItemCss, !isSeriesVisible(label) && css({ opacity: '0.35' })]}
						onclick={(e) => onLegendClick(label, e)}
					>
						<span class={legendDotCss} style:background={built.colorOf(label)}></span>
						{label.length > 14 ? label.slice(0, 14) + '…' : label}
					</button>
				{/each}
				<div
					role="button"
					tabindex="0"
					class={legendCollapseHandleCss}
					onclick={() => (legendCollapsed = true)}
					onkeydown={(e) => e.key === 'Enter' && (legendCollapsed = true)}
					title="Minimize legend"
				></div>
			{/if}
		</div>
	{/if}
	<div
		class={css({
			display: 'flex',
			alignItems: 'center',
			justifyContent: 'space-between',
			paddingY: '1.5',
			paddingX: '2.5',
			borderBottomWidth: '1'
		})}
	>
		<div class={css({ display: 'flex', gap: '1.5' })}>
			<button
				type="button"
				class={toolbarButtonCss}
				aria-label="Export chart as PNG"
				onclick={exportChartPng}
			>
				Export PNG
			</button>
			<button
				type="button"
				class={toolbarButtonCss}
				aria-label="Export chart data as CSV"
				onclick={exportChartCsv}
			>
				Export CSV
			</button>
		</div>
		{#if zoomActive}
			<button
				type="button"
				class={toolbarButtonCss}
				aria-label="Reset chart zoom"
				onclick={resetZoom}
			>
				Reset zoom
			</button>
		{/if}
	</div>
	<div
		class={css({ position: 'relative', width: '100%', overflow: 'hidden', contain: 'content' })}
		style="height: {height}px"
	>
		{#if data.length === 0}
			<div
				class={css({
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'center',
					height: '100%',
					color: 'fg.muted',
					fontSize: 'xs'
				})}
			>
				<span>No data to display</span>
			</div>
		{:else if chartType === 'pie' && built.panes.length > 1}
			<div class={css({ display: 'flex', width: '100%', height: '100%' })}>
				{#each built.panes as pane (pane.key)}
					<div class={css({ flex: '1', display: 'flex', flexDirection: 'column', minWidth: '0' })}>
						<div class={piePaneLabelCss}>{pane.label}</div>
						<div class={css({ flex: '1', minHeight: '0' })}>
							<Chart
								definition={pane.definition}
								ariaLabel={chartAriaLabel()}
								height={height - TITLE_HEIGHT - 18}
								onRender={onChartRender}
							/>
						</div>
					</div>
				{/each}
			</div>
		{:else}
			<div class={css({ width: '100%', height: '100%' })}>
				{#if built.panes[0]}
					{#if titleText}
						<div class={chartTitleCss}>{titleText}</div>
					{/if}
					<div
						class={css({ width: '100%' })}
						style="height: {height - (titleText ? TITLE_HEIGHT : 0)}px"
					>
						<Chart
							definition={built.panes[0].definition}
							ariaLabel={chartAriaLabel()}
							height={height - (titleText ? TITLE_HEIGHT : 0)}
							onRender={onChartRender}
						/>
					</div>
				{/if}
			</div>
		{/if}
		{#if built.seriesLabels.length > 0 && (legendPosition === 'left' || legendPosition === 'right')}
			<div class={sidePanelCss}>
				{#if legendPosition === 'right'}
					<button
						class={sideTabCss}
						onclick={() => (legendCollapsed = !legendCollapsed)}
						title={legendCollapsed ? 'Show legend' : 'Hide legend'}
					>
						{#if legendCollapsed}
							<ChevronLeft size={11} />
						{:else}
							<ChevronRight size={11} />
						{/if}
					</button>
				{/if}
				{#if !legendCollapsed}
					<div class={sideItemsCss}>
						{#each legendLabels() as label (label)}
							<button
								type="button"
								class={[legendItemCss, !isSeriesVisible(label) && css({ opacity: '0.35' })]}
								onclick={(e) => onLegendClick(label, e)}
							>
								<span class={legendDotCss} style:background={built.colorOf(label)}></span>
								{label.length > 14 ? label.slice(0, 14) + '…' : label}
							</button>
						{/each}
					</div>
				{/if}
				{#if legendPosition === 'left'}
					<button
						class={sideTabCss}
						onclick={() => (legendCollapsed = !legendCollapsed)}
						title={legendCollapsed ? 'Show legend' : 'Hide legend'}
					>
						{#if legendCollapsed}
							<ChevronRight size={11} />
						{:else}
							<ChevronLeft size={11} />
						{/if}
					</button>
				{/if}
			</div>
		{/if}
	</div>
	{#if built.seriesLabels.length > 0 && legendPosition === 'bottom'}
		<div class={legendBottomFullCss} data-legend-group>
			{#if legendCollapsed}
				<button
					type="button"
					class={legendPillCss}
					onclick={() => (legendCollapsed = false)}
					title="Show legend"
				>
					{#each legendLabels().slice(0, 12) as label (label)}
						<span
							class={[legendPillDotCss, !isSeriesVisible(label) && css({ opacity: '0.3' })]}
							style:background={built.colorOf(label)}
						></span>
					{/each}
				</button>
			{:else}
				{#each legendLabels() as label (label)}
					<button
						type="button"
						class={[legendItemCss, !isSeriesVisible(label) && css({ opacity: '0.35' })]}
						onclick={(e) => onLegendClick(label, e)}
					>
						<span class={legendDotCss} style:background={built.colorOf(label)}></span>
						{label.length > 14 ? label.slice(0, 14) + '…' : label}
					</button>
				{/each}
				<div
					role="button"
					tabindex="0"
					class={legendCollapseHandleCss}
					onclick={() => (legendCollapsed = true)}
					onkeydown={(e) => e.key === 'Enter' && (legendCollapsed = true)}
					title="Minimize legend"
				></div>
			{/if}
		</div>
	{/if}
</div>
