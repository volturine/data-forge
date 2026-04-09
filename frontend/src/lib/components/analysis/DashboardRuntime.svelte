<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/stores';
	import { createQuery } from '@tanstack/svelte-query';
	import { get } from 'svelte/store';
	import { getDashboard, runDashboard } from '$lib/api/analysis';
	import type {
		AnalysisDateRangeValue,
		DashboardDetailResponse,
		DashboardSelectionFilter,
		DashboardSelectionValue,
		DashboardWidget,
		DashboardWidgetPage,
		DashboardWidgetRunResult
	} from '$lib/types/analysis';
	import {
		getAffectedWidgetIds,
		parseDashboardVariableState,
		serializeDashboardVariableState
	} from '$lib/utils/dashboard-state';
	import ChartPreview from '$lib/components/pipeline/ChartPreview.svelte';
	import DataTable from '$lib/components/common/DataTable.svelte';
	import { css, button, input, spinner } from '$lib/styles/panda';

	interface Props {
		analysisId: string;
		dashboardId: string;
	}

	const { analysisId, dashboardId }: Props = $props();

	let variableState = $state<Record<string, unknown>>({});
	let widgetResults = $state<Record<string, DashboardWidgetRunResult>>({});
	let widgetPages = $state<Record<string, DashboardWidgetPage>>({});
	let widgetSearch = $state<Record<string, string>>({});
	let loadingWidgetIds = $state<string[]>([]);
	let chartSelectionFilters = $state<
		Record<string, DashboardSelectionFilter & { source_tab_id: string | null }>
	>({});
	let chartSelectionResetTokens = $state<Record<string, number>>({});
	let refreshError = $state<string | null>(null);
	let debounceTimer = $state<number | null>(null);
	let hydrated = $state(false);

	const detailQuery = createQuery(() => ({
		queryKey: ['dashboard', analysisId, dashboardId],
		queryFn: async (): Promise<DashboardDetailResponse> => {
			const result = await getDashboard(analysisId, dashboardId);
			if (result.isErr()) throw new Error(result.error.message);
			return result.value;
		},
		retry: false
	}));

	const widgetList = $derived(detailQuery.data?.dashboard.widgets ?? []);
	const dashboardVariables = $derived(detailQuery.data?.variables ?? []);
	const widgetDependencies = $derived(detailQuery.data?.widget_dependencies ?? {});
	const activeSelectionEntries = $derived(Object.entries(chartSelectionFilters));

	$effect(() => {
		const detail = detailQuery.data;
		if (!detail || hydrated) return;
		variableState = parseDashboardVariableState(detail.variables, get(page).url.searchParams);
		for (const widget of detail.dashboard.widgets) {
			if (widget.type !== 'dataset_preview') continue;
			const size = Number(widget.config.page_size ?? 25) || 25;
			widgetPages[widget.id] = { page: 1, page_size: size };
		}
		hydrated = true;
		void refreshWidgets();
	});

	function updateUrl(nextState: Record<string, unknown>) {
		const params = serializeDashboardVariableState(dashboardVariables, nextState);
		const next =
			resolve('/analysis/[id]/dashboards/[dashboardId]', {
				id: analysisId,
				dashboardId
			}) + (params.size > 0 ? `?${params.toString()}` : '');
		window.history.replaceState(window.history.state, '', next);
	}

	async function refreshWidgets(widgetIds?: string[]) {
		const ids = widgetIds ?? widgetList.map((widget) => widget.id);
		loadingWidgetIds = Array.from(new Set([...loadingWidgetIds, ...ids]));
		refreshError = null;
		const result = await runDashboard(analysisId, dashboardId, {
			variable_values: variableState,
			widget_ids: widgetIds,
			widget_page: widgetPages,
			selection_filters: Object.fromEntries(
				Object.entries(chartSelectionFilters).map(([widgetId, filter]) => [
					widgetId,
					{ column: filter.column, values: filter.values }
				])
			)
		});
		result.match(
			(payload) => {
				const next = { ...widgetResults };
				for (const widget of payload.widgets) {
					next[widget.widget_id] = widget;
				}
				widgetResults = next;
				loadingWidgetIds = loadingWidgetIds.filter((id) => !ids.includes(id));
			},
			(error) => {
				refreshError = error.message;
				loadingWidgetIds = loadingWidgetIds.filter((id) => !ids.includes(id));
			}
		);
	}

	function scheduleVariableRefresh(variableId: string) {
		if (debounceTimer !== null) window.clearTimeout(debounceTimer);
		const affected = getAffectedWidgetIds(widgetDependencies, variableId);
		debounceTimer = window.setTimeout(() => {
			void refreshWidgets(affected.length ? affected : undefined);
			debounceTimer = null;
		}, 300);
	}

	function setVariable(id: string, value: unknown) {
		const nextState = { ...variableState, [id]: value };
		variableState = nextState;
		updateUrl(nextState);
		scheduleVariableRefresh(id);
	}

	function widgetResult(widgetId: string): DashboardWidgetRunResult | null {
		return widgetResults[widgetId] ?? null;
	}

	function isWidgetLoading(widgetId: string): boolean {
		return loadingWidgetIds.includes(widgetId);
	}

	function setDatasetPage(widgetId: string, pageValue: number) {
		const current = widgetPages[widgetId] ?? { page: 1, page_size: 25 };
		widgetPages = { ...widgetPages, [widgetId]: { ...current, page: pageValue } };
		void refreshWidgets([widgetId]);
	}

	function setWidgetSearch(widgetId: string, value: string) {
		widgetSearch = { ...widgetSearch, [widgetId]: value };
	}

	function filteredDatasetRows(
		widgetId: string,
		rows: Record<string, unknown>[]
	): Record<string, unknown>[] {
		const term = (widgetSearch[widgetId] ?? '').trim().toLowerCase();
		if (!term) return rows;
		return rows.filter((row) =>
			Object.values(row).some((value) =>
				String(value ?? '')
					.toLowerCase()
					.includes(term)
			)
		);
	}

	function variableSummary(value: Record<string, unknown>): string {
		return JSON.stringify(value);
	}

	function selectionSummary(values: DashboardSelectionValue[]): string {
		return values.map(String).join(', ');
	}

	function chartSelectionTarget(
		widget: DashboardWidget
	): { column: string; source_tab_id: string | null } | null {
		if (widget.type !== 'chart') return null;
		if (!widget.config.selection_filters_widgets) return null;
		const column = String(
			widget.config.selection_filter_column ?? widget.config.x_column ?? ''
		).trim();
		if (!column) return null;
		return { column, source_tab_id: widget.source_tab_id ?? null };
	}

	function affectedSelectionWidgetIds(
		sourceWidgetId: string,
		sourceTabId: string | null | undefined
	): string[] {
		if (!sourceTabId) return [];
		return widgetList
			.filter((widget) => widget.id !== sourceWidgetId && widget.source_tab_id === sourceTabId)
			.map((widget) => widget.id);
	}

	function handleChartSelection(
		widget: DashboardWidget,
		selectedValues: DashboardSelectionValue[]
	) {
		const target = chartSelectionTarget(widget);
		const next = { ...chartSelectionFilters };
		if (!target || selectedValues.length === 0) {
			delete next[widget.id];
		} else {
			next[widget.id] = {
				column: target.column,
				values: selectedValues,
				source_tab_id: target.source_tab_id
			};
		}
		chartSelectionFilters = next;
		const affected = affectedSelectionWidgetIds(widget.id, widget.source_tab_id);
		if (affected.length > 0) {
			void refreshWidgets(affected);
		}
	}

	function clearChartSelection(widgetId: string) {
		const filter = chartSelectionFilters[widgetId];
		if (!filter) return;
		const next = { ...chartSelectionFilters };
		delete next[widgetId];
		chartSelectionFilters = next;
		chartSelectionResetTokens = {
			...chartSelectionResetTokens,
			[widgetId]: (chartSelectionResetTokens[widgetId] ?? 0) + 1
		};
		const affected = affectedSelectionWidgetIds(widgetId, filter.source_tab_id);
		if (affected.length > 0) {
			void refreshWidgets(affected);
		}
	}

	function clearAllChartSelections() {
		const affected: string[] = [];
		for (const [widgetId, filter] of Object.entries(chartSelectionFilters)) {
			for (const affectedId of affectedSelectionWidgetIds(widgetId, filter.source_tab_id)) {
				if (!affected.includes(affectedId)) {
					affected.push(affectedId);
				}
			}
		}
		chartSelectionFilters = {};
		chartSelectionResetTokens = Object.fromEntries(
			widgetList
				.filter((widget) => widget.type === 'chart')
				.map((widget) => [widget.id, (chartSelectionResetTokens[widget.id] ?? 0) + 1])
		);
		if (affected.length > 0) {
			void refreshWidgets(affected);
		}
	}
</script>

<div
	data-testid="dashboard-runtime"
	class={css({ display: 'flex', flexDirection: 'column', gap: '4', padding: '5' })}
>
	<div
		class={css({
			display: 'flex',
			alignItems: 'center',
			justifyContent: 'space-between',
			gap: '3'
		})}
	>
		<div>
			<h1 data-testid="dashboard-title" class={css({ margin: '0', fontSize: '2xl' })}>
				{detailQuery.data?.dashboard.name ?? 'Dashboard'}
			</h1>
			<p class={css({ marginTop: '1', marginBottom: '0', color: 'fg.muted' })}>
				{detailQuery.data?.dashboard.description ?? 'Interactive runtime for this analysis.'}
			</p>
		</div>
		<button
			data-testid="dashboard-refresh"
			class={button({ size: 'sm' })}
			type="button"
			onclick={() => refreshWidgets()}
		>
			Refresh
		</button>
	</div>

	<div
		class={css({
			display: 'grid',
			gap: '3',
			gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))'
		})}
	>
		{#each dashboardVariables as variable (variable.id)}
			<div
				data-testid="runtime-variable"
				data-variable-id={variable.id}
				class={css({ borderWidth: '1', backgroundColor: 'bg.primary', padding: '3' })}
			>
				<span
					class={css({ display: 'block', marginBottom: '1', fontSize: 'sm', fontWeight: 'medium' })}
				>
					{variable.label}
				</span>
				{#if variable.type === 'number'}
					<input
						class={input()}
						type="number"
						value={String(variableState[variable.id] ?? variable.default_value)}
						oninput={(event) => setVariable(variable.id, Number(event.currentTarget.value))}
					/>
				{:else if variable.type === 'boolean'}
					<select
						class={input()}
						value={String(variableState[variable.id] ?? variable.default_value)}
						onchange={(event) => setVariable(variable.id, event.currentTarget.value === 'true')}
					>
						<option value="true">true</option>
						<option value="false">false</option>
					</select>
				{:else if variable.type === 'date'}
					<input
						class={input()}
						type="date"
						value={String(variableState[variable.id] ?? variable.default_value)}
						oninput={(event) => setVariable(variable.id, event.currentTarget.value)}
					/>
				{:else if variable.type === 'date_range'}
					<div class={css({ display: 'grid', gap: '2', gridTemplateColumns: '1fr 1fr' })}>
						<input
							class={input()}
							type="date"
							value={String(
								(variableState[variable.id] as AnalysisDateRangeValue)?.start ??
									(variable.default_value as AnalysisDateRangeValue).start
							)}
							oninput={(event) =>
								setVariable(variable.id, {
									...(variableState[variable.id] as AnalysisDateRangeValue),
									start: event.currentTarget.value,
									end:
										(variableState[variable.id] as AnalysisDateRangeValue)?.end ??
										(variable.default_value as AnalysisDateRangeValue).end
								})}
						/>
						<input
							class={input()}
							type="date"
							value={String(
								(variableState[variable.id] as AnalysisDateRangeValue)?.end ??
									(variable.default_value as AnalysisDateRangeValue).end
							)}
							oninput={(event) =>
								setVariable(variable.id, {
									start:
										(variableState[variable.id] as AnalysisDateRangeValue)?.start ??
										(variable.default_value as AnalysisDateRangeValue).start,
									end: event.currentTarget.value
								})}
						/>
					</div>
				{:else if variable.type === 'multi_select'}
					<select
						class={input()}
						multiple
						size="4"
						onchange={(event) =>
							setVariable(
								variable.id,
								Array.from(event.currentTarget.selectedOptions).map((option) => option.value)
							)}
					>
						{#each variable.options as option (option.label)}
							<option
								value={String(option.value)}
								selected={Array.isArray(variableState[variable.id])
									? (variableState[variable.id] as unknown[])
											.map(String)
											.includes(String(option.value))
									: false}
							>
								{option.label}
							</option>
						{/each}
					</select>
				{:else if variable.options.length > 0}
					<select
						class={input()}
						value={String(variableState[variable.id] ?? variable.default_value)}
						onchange={(event) => setVariable(variable.id, event.currentTarget.value)}
					>
						{#each variable.options as option (option.label)}
							<option value={String(option.value)}>{option.label}</option>
						{/each}
					</select>
				{:else}
					<input
						class={input()}
						value={String(variableState[variable.id] ?? variable.default_value)}
						oninput={(event) => setVariable(variable.id, event.currentTarget.value)}
					/>
				{/if}
			</div>
		{/each}
	</div>

	{#if refreshError}
		<div
			class={css({
				borderWidth: '1',
				backgroundColor: 'bg.error',
				color: 'fg.error',
				padding: '3'
			})}
		>
			{refreshError}
		</div>
	{/if}

	{#if activeSelectionEntries.length > 0}
		<div
			data-testid="selection-filter-bar"
			class={css({
				display: 'flex',
				flexWrap: 'wrap',
				alignItems: 'center',
				gap: '2',
				borderWidth: '1',
				backgroundColor: 'bg.secondary',
				padding: '3'
			})}
		>
			<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>Selection filters</span>
			{#each activeSelectionEntries as [widgetId, filter] (`selection-${widgetId}`)}
				<button
					type="button"
					class={button({ size: 'sm', variant: 'secondary' })}
					onclick={() => clearChartSelection(widgetId)}
				>
					{widgetList.find((widget) => widget.id === widgetId)?.title ?? widgetId}: {filter.column}
					in {selectionSummary(filter.values)}
				</button>
			{/each}
			<button
				type="button"
				data-testid="clear-all-selections"
				class={button({ size: 'sm', variant: 'secondary' })}
				onclick={clearAllChartSelections}
			>
				Clear all
			</button>
		</div>
	{/if}

	<div
		class={css({ display: 'grid', gap: '4', gridTemplateColumns: 'repeat(12, minmax(0, 1fr))' })}
	>
		{#each widgetList as widget (widget.id)}
			{@const result = widgetResult(widget.id)}
			<div
				data-testid="runtime-widget"
				data-widget-type={widget.type}
				data-widget-id={widget.id}
				class={css({
					gridColumn: `span ${Math.max(1, Math.min(12, Number(detailQuery.data?.dashboard.layout.find((item) => item.widget_id === widget.id)?.w ?? 6)))}`,
					borderWidth: '1',
					backgroundColor: 'bg.primary',
					padding: '4'
				})}
			>
				<div
					class={css({
						marginBottom: '3',
						display: 'flex',
						alignItems: 'start',
						justifyContent: 'space-between',
						gap: '3'
					})}
				>
					<div>
						<h2 data-testid="widget-title" class={css({ margin: '0', fontSize: 'lg' })}>
							{widget.title}
						</h2>
						<p
							class={css({ marginTop: '1', marginBottom: '0', color: 'fg.muted', fontSize: 'xs' })}
						>
							Source: {widget.source_tab_id ?? 'presentation'} | Last refresh: {result?.last_refresh_at ??
								'not yet'}
						</p>
						<p
							class={css({ marginTop: '1', marginBottom: '0', color: 'fg.muted', fontSize: 'xs' })}
						>
							Variables: {result
								? variableSummary(result.variable_state)
								: variableSummary(variableState)}
						</p>
					</div>
					{#if isWidgetLoading(widget.id)}
						<div class={spinner()}></div>
					{/if}
				</div>

				{#if result?.status === 'error'}
					<div
						class={css({
							borderWidth: '1',
							backgroundColor: 'bg.error',
							color: 'fg.error',
							padding: '3'
						})}
					>
						{result.error}
					</div>
				{:else if widget.type === 'text_header' && result?.header}
					{#if result.header.level === 1}
						<h1 class={css({ margin: '0', fontSize: '2xl' })}>{result.header.text}</h1>
					{:else if result.header.level === 2}
						<h2 class={css({ margin: '0', fontSize: 'xl' })}>{result.header.text}</h2>
					{:else}
						<h3 class={css({ margin: '0', fontSize: 'lg' })}>{result.header.text}</h3>
					{/if}
				{:else if widget.type === 'metric_kpi' && result?.metric}
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
						<span class={css({ fontSize: 'sm', color: 'fg.muted' })}>{result.metric.label}</span>
						<strong class={css({ fontSize: '3xl' })}>{result.metric.value}</strong>
						{#if result.metric.comparison !== undefined && result.metric.comparison !== null}
							<span class={css({ fontSize: 'sm', color: 'fg.muted' })}
								>Comparison: {result.metric.comparison}</span
							>
						{/if}
					</div>
				{:else if widget.type === 'chart' && result?.chart}
					<ChartPreview
						data={result.chart.data}
						chartType={String(result.chart.config.chart_type ?? 'bar') as
							| 'bar'
							| 'horizontal_bar'
							| 'area'
							| 'heatgrid'
							| 'line'
							| 'pie'
							| 'histogram'
							| 'scatter'
							| 'boxplot'}
						config={result.chart.config}
						metadata={result.chart.metadata}
						height={320}
						selectionResetToken={chartSelectionResetTokens[widget.id] ?? 0}
						onSelectionChange={(selectedValues) => handleChartSelection(widget, selectedValues)}
					/>
				{:else if widget.type === 'dataset_preview' && result?.dataset}
					{@const localSearchEnabled = Boolean(widget.config.searchable)}
					{@const visibleRows = filteredDatasetRows(widget.id, result.dataset.rows)}
					{#if localSearchEnabled}
						<div
							class={css({
								marginBottom: '3',
								display: 'flex',
								alignItems: 'center',
								justifyContent: 'space-between',
								gap: '3'
							})}
						>
							<input
								data-testid="widget-search"
								class={input()}
								placeholder="Search current page"
								value={widgetSearch[widget.id] ?? ''}
								oninput={(event) => setWidgetSearch(widget.id, event.currentTarget.value)}
							/>
							<span class={css({ whiteSpace: 'nowrap', fontSize: 'xs', color: 'fg.muted' })}>
								{visibleRows.length}/{result.dataset.rows.length} rows
							</span>
						</div>
					{/if}
					<DataTable
						columns={result.dataset.columns}
						data={visibleRows}
						columnTypes={result.dataset.column_types}
						showHeader
						showPagination
						showFooter={false}
						pagination={{
							page: result.dataset.page,
							canPrev: result.dataset.page > 1,
							canNext: result.dataset.rows.length === result.dataset.page_size,
							onPrev: () => setDatasetPage(widget.id, result.dataset!.page - 1),
							onNext: () => setDatasetPage(widget.id, result.dataset!.page + 1)
						}}
					/>
				{:else}
					<div class={css({ color: 'fg.muted', fontSize: 'sm' })}>No data for this widget.</div>
				{/if}
			</div>
		{/each}
	</div>
</div>
