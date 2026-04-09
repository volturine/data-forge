<script lang="ts">
	import { resolve } from '$app/paths';
	import type {
		AnalysisDateRangeValue,
		AnalysisTab,
		AnalysisVariableDefinition,
		AnalysisVariableOption,
		DashboardDefinition,
		DashboardWidget,
		DashboardWidgetType
	} from '$lib/types/analysis';
	import {
		createDashboardDraft,
		createVariableDraft,
		createWidgetDraft
	} from '$lib/utils/dashboard-state';
	import { css, button, input, label } from '$lib/styles/panda';
	import { Plus, Trash2, ArrowDown, ArrowUp, ExternalLink } from 'lucide-svelte';

	interface Props {
		analysisId: string;
		tabs: AnalysisTab[];
		variables?: AnalysisVariableDefinition[];
		dashboards?: DashboardDefinition[];
		readOnly?: boolean;
	}

	let {
		analysisId,
		tabs,
		variables = $bindable([]),
		dashboards = $bindable([]),
		readOnly = false
	}: Props = $props();

	let selectedDashboardId = $state<string | null>(null);
	const GRID_COLUMNS = 12;
	const LAYOUT_ROW_HEIGHT = 72;
	const MIN_LAYOUT_ROWS = 4;
	const MAX_LAYOUT_ROWS = 24;
	let layoutCanvasRef = $state<HTMLDivElement>();

	const selectedDashboard = $derived(
		dashboards.find((dashboard) => dashboard.id === selectedDashboardId) ?? dashboards[0] ?? null
	);

	$effect(() => {
		if (!selectedDashboardId && dashboards[0]) {
			selectedDashboardId = dashboards[0].id;
		}
		if (selectedDashboardId && dashboards.some((dashboard) => dashboard.id === selectedDashboardId))
			return;
		selectedDashboardId = dashboards[0]?.id ?? null;
	});

	function updateVariable(index: number, updates: Partial<AnalysisVariableDefinition>) {
		variables = variables.map((variable, variableIndex) =>
			variableIndex === index ? { ...variable, ...updates } : variable
		);
	}

	function addVariable() {
		variables = [...variables, createVariableDraft(variables.length)];
	}

	function removeVariable(index: number) {
		variables = variables.filter((_, variableIndex) => variableIndex !== index);
	}

	function addOption(index: number) {
		const variable = variables[index];
		if (!variable) return;
		const options = [
			...variable.options,
			{ label: 'Option', value: 'value' } satisfies AnalysisVariableOption
		];
		updateVariable(index, { options, option_source: null });
	}

	function updateOption(
		index: number,
		optionIndex: number,
		updates: Partial<AnalysisVariableOption>
	) {
		const variable = variables[index];
		if (!variable) return;
		const options = variable.options.map((option, currentIndex) =>
			currentIndex === optionIndex ? { ...option, ...updates } : option
		);
		updateVariable(index, { options });
	}

	function removeOption(index: number, optionIndex: number) {
		const variable = variables[index];
		if (!variable) return;
		updateVariable(index, {
			options: variable.options.filter((_, currentIndex) => currentIndex !== optionIndex)
		});
	}

	function setVariableType(index: number, type: AnalysisVariableDefinition['type']) {
		if (type === 'number') {
			updateVariable(index, { type, default_value: 0, options: [], option_source: null });
			return;
		}
		if (type === 'boolean') {
			updateVariable(index, { type, default_value: false, options: [], option_source: null });
			return;
		}
		if (type === 'multi_select') {
			updateVariable(index, { type, default_value: [], options: [], option_source: null });
			return;
		}
		if (type === 'date') {
			updateVariable(index, {
				type,
				default_value: '2024-01-01',
				options: [],
				option_source: null
			});
			return;
		}
		if (type === 'date_range') {
			updateVariable(index, {
				type,
				default_value: { start: '2024-01-01', end: '2024-12-31' } satisfies AnalysisDateRangeValue,
				options: [],
				option_source: null
			});
			return;
		}
		updateVariable(index, { type, default_value: '', options: [], option_source: null });
	}

	function updateVariableDefault(index: number, value: unknown) {
		updateVariable(index, { default_value: value as AnalysisVariableDefinition['default_value'] });
	}

	function updateDashboard(dashboardId: string, updates: Partial<DashboardDefinition>) {
		dashboards = dashboards.map((dashboard) =>
			dashboard.id === dashboardId ? { ...dashboard, ...updates } : dashboard
		);
	}

	function addDashboard() {
		const next = createDashboardDraft(dashboards.length);
		dashboards = [...dashboards, next];
		selectedDashboardId = next.id;
	}

	function removeDashboard(dashboardId: string) {
		dashboards = dashboards.filter((dashboard) => dashboard.id !== dashboardId);
	}

	function updateSelectedWidget(widgetId: string, updates: Partial<DashboardWidget>) {
		const dashboard = selectedDashboard;
		if (!dashboard) return;
		updateDashboard(dashboard.id, {
			widgets: dashboard.widgets.map((widget) =>
				widget.id === widgetId ? { ...widget, ...updates } : widget
			)
		});
	}

	function updateSelectedLayout(widgetId: string, updates: Record<string, number>) {
		const dashboard = selectedDashboard;
		if (!dashboard) return;
		updateDashboard(dashboard.id, {
			layout: dashboard.layout.map((item) =>
				item.widget_id === widgetId ? { ...item, ...updates } : item
			)
		});
	}

	function addWidget(type: DashboardWidgetType) {
		const dashboard = selectedDashboard;
		if (!dashboard) return;
		const sourceTabId = tabs[0]?.id ?? null;
		const draft = createWidgetDraft(type, sourceTabId, dashboard.widgets.length);
		updateDashboard(dashboard.id, {
			widgets: [...dashboard.widgets, draft.widget],
			layout: [...dashboard.layout, draft.layout]
		});
	}

	function removeWidget(widgetId: string) {
		const dashboard = selectedDashboard;
		if (!dashboard) return;
		updateDashboard(dashboard.id, {
			widgets: dashboard.widgets.filter((widget) => widget.id !== widgetId),
			layout: dashboard.layout.filter((item) => item.widget_id !== widgetId)
		});
	}

	function moveWidget(widgetId: string, direction: -1 | 1) {
		const dashboard = selectedDashboard;
		if (!dashboard) return;
		const index = dashboard.widgets.findIndex((widget) => widget.id === widgetId);
		const nextIndex = index + direction;
		if (index < 0 || nextIndex < 0 || nextIndex >= dashboard.widgets.length) return;
		const widgets = [...dashboard.widgets];
		const [widget] = widgets.splice(index, 1);
		widgets.splice(nextIndex, 0, widget);
		updateDashboard(dashboard.id, { widgets });
	}

	function widgetLayout(widgetId: string) {
		return selectedDashboard?.layout.find((item) => item.widget_id === widgetId) ?? null;
	}

	function clamp(value: number, min: number, max: number): number {
		return Math.min(max, Math.max(min, value));
	}

	function layoutCanvasRows(): number {
		if (!selectedDashboard || selectedDashboard.layout.length === 0) {
			return MIN_LAYOUT_ROWS;
		}
		return Math.max(
			MIN_LAYOUT_ROWS,
			...selectedDashboard.layout.map((item) => clamp(item.y + item.h, 1, MAX_LAYOUT_ROWS))
		);
	}

	function layoutCanvasStyle(): string {
		return `height:${layoutCanvasRows() * LAYOUT_ROW_HEIGHT}px;`;
	}

	function layoutTileStyle(widgetId: string): string {
		const item = widgetLayout(widgetId);
		if (!item) return '';
		return [
			`left:calc(${(item.x / GRID_COLUMNS) * 100}% + 4px)`,
			`top:${item.y * LAYOUT_ROW_HEIGHT + 4}px`,
			`width:calc(${(item.w / GRID_COLUMNS) * 100}% - 8px)`,
			`height:${item.h * LAYOUT_ROW_HEIGHT - 8}px`
		].join(';');
	}

	function beginLayoutGesture(event: PointerEvent, widgetId: string, mode: 'move' | 'resize') {
		if (readOnly || !layoutCanvasRef) return;
		const item = widgetLayout(widgetId);
		if (!item) return;
		event.preventDefault();
		event.stopPropagation();
		const rect = layoutCanvasRef.getBoundingClientRect();
		const colWidth = rect.width / GRID_COLUMNS;
		const start = { x: item.x, y: item.y, w: item.w, h: item.h };
		const onMove = (nextEvent: PointerEvent) => {
			const deltaCols = Math.round((nextEvent.clientX - event.clientX) / colWidth);
			const deltaRows = Math.round((nextEvent.clientY - event.clientY) / LAYOUT_ROW_HEIGHT);
			if (mode === 'move') {
				updateSelectedLayout(widgetId, {
					x: clamp(start.x + deltaCols, 0, GRID_COLUMNS - start.w),
					y: clamp(start.y + deltaRows, 0, MAX_LAYOUT_ROWS - start.h)
				});
				return;
			}
			updateSelectedLayout(widgetId, {
				w: clamp(start.w + deltaCols, 1, GRID_COLUMNS - start.x),
				h: clamp(start.h + deltaRows, 1, 8)
			});
		};
		const onUp = () => {
			window.removeEventListener('pointermove', onMove);
			window.removeEventListener('pointerup', onUp);
		};
		window.addEventListener('pointermove', onMove);
		window.addEventListener('pointerup', onUp);
	}
</script>

<div
	data-testid="dashboard-builder"
	class={css({ display: 'flex', height: 'full', flexDirection: 'column', gap: '5', padding: '5' })}
>
	<div
		class={css({
			display: 'grid',
			gap: '5',
			gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))'
		})}
	>
		<section class={css({ borderWidth: '1', backgroundColor: 'bg.primary', padding: '4' })}>
			<div
				class={css({
					marginBottom: '4',
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'space-between'
				})}
			>
				<h2 class={css({ margin: '0', fontSize: 'lg' })}>Variables</h2>
				<button
					class={button({ size: 'sm' })}
					type="button"
					data-testid="add-variable"
					onclick={addVariable}
					disabled={readOnly}
				>
					<Plus size={14} /> Add variable
				</button>
			</div>
			<div class={css({ display: 'flex', flexDirection: 'column', gap: '4' })}>
				{#if variables.length === 0}
					<p class={css({ margin: '0', color: 'fg.muted', fontSize: 'sm' })}>
						Add analysis-scoped variables for runtime filters and thresholds.
					</p>
				{/if}
				{#each variables as variable, index (variable.id)}
					<div class={css({ borderWidth: '1', backgroundColor: 'bg.secondary', padding: '3' })}>
						<div
							class={css({
								marginBottom: '3',
								display: 'grid',
								gap: '3',
								gridTemplateColumns: '1fr 1fr auto'
							})}
						>
							<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
								<span class={label({ variant: 'field' })}>Label</span>
								<input
									class={input()}
									value={variable.label}
									oninput={(event) => updateVariable(index, { label: event.currentTarget.value })}
									disabled={readOnly}
								/>
							</div>
							<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
								<span class={label({ variant: 'field' })}>ID</span>
								<input
									class={input()}
									value={variable.id}
									oninput={(event) => updateVariable(index, { id: event.currentTarget.value })}
									disabled={readOnly}
								/>
							</div>
							<button
								type="button"
								class={css({
									alignSelf: 'end',
									display: 'flex',
									height: 'row',
									width: 'row',
									alignItems: 'center',
									justifyContent: 'center',
									borderWidth: '1',
									backgroundColor: 'transparent',
									color: 'fg.muted'
								})}
								onclick={() => removeVariable(index)}
								disabled={readOnly}
							>
								<Trash2 size={14} />
							</button>
						</div>
						<div
							class={css({
								marginBottom: '3',
								display: 'grid',
								gap: '3',
								gridTemplateColumns: '1fr 1fr auto'
							})}
						>
							<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
								<span class={label({ variant: 'field' })}>Type</span>
								<select
									class={input()}
									value={variable.type}
									onchange={(event) =>
										setVariableType(
											index,
											event.currentTarget.value as AnalysisVariableDefinition['type']
										)}
									disabled={readOnly}
								>
									<option value="string">string</option>
									<option value="number">number</option>
									<option value="boolean">boolean</option>
									<option value="single_select">single select</option>
									<option value="multi_select">multi select</option>
									<option value="date">date</option>
									<option value="date_range">date range</option>
								</select>
							</div>
							<div class={css({ display: 'flex', flexDirection: 'column', gap: '1' })}>
								<span class={label({ variant: 'field' })}>Default</span>
								{#if variable.type === 'number'}
									<input
										class={input()}
										type="number"
										value={String(variable.default_value)}
										oninput={(event) =>
											updateVariableDefault(index, Number(event.currentTarget.value))}
										disabled={readOnly}
									/>
								{:else if variable.type === 'boolean'}
									<select
										class={input()}
										value={String(variable.default_value)}
										onchange={(event) =>
											updateVariableDefault(index, event.currentTarget.value === 'true')}
										disabled={readOnly}
									>
										<option value="true">true</option>
										<option value="false">false</option>
									</select>
								{:else if variable.type === 'date'}
									<input
										class={input()}
										type="date"
										value={String(variable.default_value)}
										oninput={(event) => updateVariableDefault(index, event.currentTarget.value)}
										disabled={readOnly}
									/>
								{:else if variable.type === 'date_range'}
									<div class={css({ display: 'grid', gap: '2', gridTemplateColumns: '1fr 1fr' })}>
										<input
											class={input()}
											type="date"
											value={(variable.default_value as AnalysisDateRangeValue).start}
											oninput={(event) =>
												updateVariableDefault(index, {
													...(variable.default_value as AnalysisDateRangeValue),
													start: event.currentTarget.value
												})}
											disabled={readOnly}
										/>
										<input
											class={input()}
											type="date"
											value={(variable.default_value as AnalysisDateRangeValue).end}
											oninput={(event) =>
												updateVariableDefault(index, {
													...(variable.default_value as AnalysisDateRangeValue),
													end: event.currentTarget.value
												})}
											disabled={readOnly}
										/>
									</div>
								{:else if variable.type === 'multi_select'}
									<input
										class={input()}
										type="text"
										value={Array.isArray(variable.default_value)
											? variable.default_value.join(',')
											: ''}
										oninput={(event) =>
											updateVariableDefault(
												index,
												event.currentTarget.value
													.split(',')
													.map((item) => item.trim())
													.filter(Boolean)
											)}
										disabled={readOnly}
									/>
								{:else}
									<input
										class={input()}
										value={String(variable.default_value)}
										oninput={(event) => updateVariableDefault(index, event.currentTarget.value)}
										disabled={readOnly}
									/>
								{/if}
							</div>
							<label
								class={css({
									display: 'flex',
									alignItems: 'end',
									gap: '2',
									paddingBottom: '2',
									fontSize: 'sm'
								})}
							>
								<input
									type="checkbox"
									checked={variable.required}
									onchange={(event) =>
										updateVariable(index, { required: event.currentTarget.checked })}
									disabled={readOnly}
								/>
								Required
							</label>
						</div>
						{#if variable.type === 'single_select' || variable.type === 'multi_select'}
							<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
								<div
									class={css({
										display: 'flex',
										alignItems: 'center',
										justifyContent: 'space-between'
									})}
								>
									<span class={css({ fontSize: 'sm', fontWeight: 'medium' })}>Options</span>
									<div class={css({ display: 'flex', gap: '2' })}>
										<button
											type="button"
											class={button({ size: 'sm', variant: 'secondary' })}
											onclick={() => addOption(index)}
											disabled={readOnly}
										>
											<Plus size={12} /> Manual
										</button>
										<button
											type="button"
											class={button({ size: 'sm', variant: 'secondary' })}
											onclick={() =>
												updateVariable(index, {
													options: [],
													option_source: { tab_id: tabs[0]?.id ?? '', column: '', limit: 100 }
												})}
											disabled={readOnly}
										>
											Source-backed
										</button>
									</div>
								</div>
								{#if variable.option_source}
									<div
										class={css({ display: 'grid', gap: '2', gridTemplateColumns: '1fr 1fr auto' })}
									>
										<select
											class={input()}
											value={variable.option_source.tab_id}
											onchange={(event) =>
												updateVariable(index, {
													option_source: {
														...variable.option_source!,
														tab_id: event.currentTarget.value
													}
												})}
											disabled={readOnly}
										>
											{#each tabs as tab (tab.id)}
												<option value={tab.id}>{tab.name}</option>
											{/each}
										</select>
										<input
											class={input()}
											value={variable.option_source.column}
											placeholder="Column"
											oninput={(event) =>
												updateVariable(index, {
													option_source: {
														...variable.option_source!,
														column: event.currentTarget.value
													}
												})}
											disabled={readOnly}
										/>
										<button
											type="button"
											class={button({ size: 'sm', variant: 'secondary' })}
											onclick={() => updateVariable(index, { option_source: null })}
											disabled={readOnly}
										>
											Clear
										</button>
									</div>
								{:else}
									{#each variable.options as option, optionIndex (`${variable.id}-${optionIndex}`)}
										<div
											class={css({
												display: 'grid',
												gap: '2',
												gridTemplateColumns: '1fr 1fr auto'
											})}
										>
											<input
												class={input()}
												value={option.label}
												oninput={(event) =>
													updateOption(index, optionIndex, { label: event.currentTarget.value })}
												disabled={readOnly}
											/>
											<input
												class={input()}
												value={String(option.value)}
												oninput={(event) =>
													updateOption(index, optionIndex, { value: event.currentTarget.value })}
												disabled={readOnly}
											/>
											<button
												type="button"
												class={button({ size: 'sm', variant: 'secondary' })}
												onclick={() => removeOption(index, optionIndex)}
												disabled={readOnly}
											>
												<Trash2 size={12} />
											</button>
										</div>
									{/each}
								{/if}
							</div>
						{/if}
					</div>
				{/each}
			</div>
		</section>

		<section class={css({ borderWidth: '1', backgroundColor: 'bg.primary', padding: '4' })}>
			<div
				class={css({
					marginBottom: '4',
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'space-between'
				})}
			>
				<h2 class={css({ margin: '0', fontSize: 'lg' })}>Dashboards</h2>
				<button
					class={button({ size: 'sm' })}
					type="button"
					data-testid="add-dashboard"
					onclick={addDashboard}
					disabled={readOnly}
				>
					<Plus size={14} /> Add dashboard
				</button>
			</div>
			<div class={css({ display: 'flex', flexWrap: 'wrap', gap: '2' })}>
				{#each dashboards as dashboard (dashboard.id)}
					<button
						type="button"
						class={css({
							borderWidth: '1',
							backgroundColor:
								selectedDashboardId === dashboard.id ? 'bg.tertiary' : 'bg.secondary',
							paddingX: '3',
							paddingY: '2',
							fontSize: 'sm'
						})}
						onclick={() => (selectedDashboardId = dashboard.id)}
					>
						{dashboard.name}
					</button>
				{/each}
			</div>
			{#if selectedDashboard}
				<div class={css({ marginTop: '4', display: 'flex', flexDirection: 'column', gap: '3' })}>
					<div class={css({ display: 'grid', gap: '3', gridTemplateColumns: '1fr auto auto' })}>
						<input
							class={input()}
							value={selectedDashboard.name}
							oninput={(event) =>
								updateDashboard(selectedDashboard.id, { name: event.currentTarget.value })}
							disabled={readOnly}
						/>
						<a
							href={resolve(`/analysis/${analysisId}/dashboards/${selectedDashboard.id}`)}
							class={button({ size: 'sm', variant: 'secondary' })}
							target="_blank"
							rel="noreferrer"
						>
							<ExternalLink size={14} /> Open runtime
						</a>
						<button
							type="button"
							class={button({ size: 'sm', variant: 'secondary' })}
							onclick={() => removeDashboard(selectedDashboard.id)}
							disabled={readOnly}
						>
							<Trash2 size={14} /> Remove
						</button>
					</div>
					<textarea
						class={input()}
						rows="3"
						value={selectedDashboard.description ?? ''}
						oninput={(event) =>
							updateDashboard(selectedDashboard.id, {
								description: event.currentTarget.value || null
							})}
						disabled={readOnly}
					></textarea>
					<div class={css({ display: 'flex', flexWrap: 'wrap', gap: '2' })}>
						<button
							class={button({ size: 'sm', variant: 'secondary' })}
							type="button"
							data-testid="add-widget-dataset"
							onclick={() => addWidget('dataset_preview')}
							disabled={readOnly}>Dataset</button
						>
						<button
							class={button({ size: 'sm', variant: 'secondary' })}
							type="button"
							data-testid="add-widget-chart"
							onclick={() => addWidget('chart')}
							disabled={readOnly}>Chart</button
						>
						<button
							class={button({ size: 'sm', variant: 'secondary' })}
							type="button"
							data-testid="add-widget-metric"
							onclick={() => addWidget('metric_kpi')}
							disabled={readOnly}>Metric</button
						>
						<button
							class={button({ size: 'sm', variant: 'secondary' })}
							type="button"
							data-testid="add-widget-header"
							onclick={() => addWidget('text_header')}
							disabled={readOnly}>Header</button
						>
					</div>
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '2' })}>
						<div
							class={css({
								display: 'flex',
								alignItems: 'center',
								justifyContent: 'space-between'
							})}
						>
							<span class={css({ fontSize: 'sm', fontWeight: 'medium' })}>Layout canvas</span>
							<span class={css({ fontSize: 'xs', color: 'fg.muted' })}>
								Drag cards to move, pull the corner to resize.
							</span>
						</div>
						<div
							bind:this={layoutCanvasRef}
							class={css({
								position: 'relative',
								borderWidth: '1',
								backgroundColor: 'bg.secondary',
								backgroundImage:
									'linear-gradient(to right, var(--colors-border-primary) 1px, transparent 1px), linear-gradient(to bottom, var(--colors-border-primary) 1px, transparent 1px)',
								backgroundSize: `calc(100% / ${GRID_COLUMNS}) ${LAYOUT_ROW_HEIGHT}px`,
								backgroundPosition: '0 0',
								overflow: 'hidden'
							})}
							style={layoutCanvasStyle()}
						>
							{#each selectedDashboard.layout as item (item.widget_id)}
								{@const widget = selectedDashboard.widgets.find(
									(entry) => entry.id === item.widget_id
								)}
								{#if widget}
									<div
										class={css({
											position: 'absolute',
											display: 'flex',
											flexDirection: 'column',
											borderWidth: '1',
											backgroundColor: 'bg.primary',
											boxShadow: 'sm'
										})}
										style={layoutTileStyle(widget.id)}
									>
										<button
											type="button"
											class={css({
												display: 'flex',
												cursor: readOnly ? 'default' : 'grab',
												alignItems: 'center',
												justifyContent: 'space-between',
												gap: '2',
												borderBottomWidth: '1',
												backgroundColor: 'bg.tertiary',
												textAlign: 'left',
												paddingX: '2',
												paddingY: '1'
											})}
											onpointerdown={(event) => beginLayoutGesture(event, widget.id, 'move')}
											aria-label={`Move ${widget.title}`}
											disabled={readOnly}
										>
											<span class={css({ fontSize: 'xs', fontWeight: 'medium' })}
												>{widget.title}</span
											>
											<span class={css({ fontSize: '2xs', color: 'fg.muted' })}>
												{item.w}x{item.h}
											</span>
										</button>
										<div
											class={css({
												flex: '1',
												padding: '2',
												fontSize: 'xs',
												color: 'fg.muted'
											})}
										>
											{widget.type}
										</div>
										<button
											type="button"
											class={css({
												position: 'absolute',
												right: '1',
												bottom: '1',
												height: '4',
												width: '4',
												cursor: readOnly ? 'default' : 'nwse-resize',
												borderRightWidth: '2',
												borderBottomWidth: '2',
												borderColor: 'fg.muted'
											})}
											onpointerdown={(event) => beginLayoutGesture(event, widget.id, 'resize')}
											aria-label={`Resize ${widget.title}`}
											disabled={readOnly}
										></button>
									</div>
								{/if}
							{/each}
						</div>
					</div>
					<div class={css({ display: 'flex', flexDirection: 'column', gap: '3' })}>
						{#each selectedDashboard.widgets as widget (widget.id)}
							{@const layout = widgetLayout(widget.id)}
							<div
								data-testid="widget-card"
								data-widget-type={widget.type}
								class={css({ borderWidth: '1', backgroundColor: 'bg.secondary', padding: '3' })}
							>
								<div
									class={css({
										marginBottom: '3',
										display: 'grid',
										gap: '3',
										gridTemplateColumns: '1fr auto auto auto'
									})}
								>
									<input
										class={input()}
										value={widget.title}
										oninput={(event) =>
											updateSelectedWidget(widget.id, { title: event.currentTarget.value })}
										disabled={readOnly}
									/>
									<button
										type="button"
										class={button({ size: 'sm', variant: 'secondary' })}
										onclick={() => moveWidget(widget.id, -1)}
										disabled={readOnly}
									>
										<ArrowUp size={12} />
									</button>
									<button
										type="button"
										class={button({ size: 'sm', variant: 'secondary' })}
										onclick={() => moveWidget(widget.id, 1)}
										disabled={readOnly}
									>
										<ArrowDown size={12} />
									</button>
									<button
										type="button"
										class={button({ size: 'sm', variant: 'secondary' })}
										onclick={() => removeWidget(widget.id)}
										disabled={readOnly}
									>
										<Trash2 size={12} />
									</button>
								</div>
								<div
									class={css({
										marginBottom: '3',
										display: 'grid',
										gap: '3',
										gridTemplateColumns: '1fr 1fr'
									})}
								>
									<select
										class={input()}
										value={widget.type}
										onchange={(event) =>
											updateSelectedWidget(widget.id, {
												type: event.currentTarget.value as DashboardWidgetType
											})}
										disabled={readOnly}
									>
										<option value="dataset_preview">dataset preview</option>
										<option value="chart">chart</option>
										<option value="metric_kpi">metric KPI</option>
										<option value="text_header">text header</option>
									</select>
									{#if widget.type !== 'text_header'}
										<select
											class={input()}
											value={widget.source_tab_id ?? tabs[0]?.id ?? ''}
											onchange={(event) =>
												updateSelectedWidget(widget.id, {
													source_tab_id: event.currentTarget.value
												})}
											disabled={readOnly}
										>
											{#each tabs as tab (tab.id)}
												<option value={tab.id}>{tab.name}</option>
											{/each}
										</select>
									{/if}
								</div>
								{#if widget.type === 'dataset_preview'}
									<input
										class={input()}
										type="number"
										value={String((widget.config.page_size as number | undefined) ?? 25)}
										oninput={(event) =>
											updateSelectedWidget(widget.id, {
												config: { ...widget.config, page_size: Number(event.currentTarget.value) }
											})}
										disabled={readOnly}
									/>
								{:else if widget.type === 'chart'}
									<div class={css({ display: 'grid', gap: '2' })}>
										<div
											class={css({ display: 'grid', gap: '2', gridTemplateColumns: '1fr 1fr 1fr' })}
										>
											<select
												class={input()}
												value={String(widget.config.chart_type ?? 'bar')}
												onchange={(event) =>
													updateSelectedWidget(widget.id, {
														config: { ...widget.config, chart_type: event.currentTarget.value }
													})}
												disabled={readOnly}
											>
												<option value="bar">bar</option>
												<option value="line">line</option>
												<option value="area">area</option>
												<option value="pie">pie</option>
												<option value="scatter">scatter</option>
												<option value="histogram">histogram</option>
											</select>
											<input
												class={input()}
												placeholder="x column"
												value={String(widget.config.x_column ?? '')}
												oninput={(event) =>
													updateSelectedWidget(widget.id, {
														config: { ...widget.config, x_column: event.currentTarget.value }
													})}
												disabled={readOnly}
											/>
											<input
												class={input()}
												placeholder="y column"
												value={String(widget.config.y_column ?? '')}
												oninput={(event) =>
													updateSelectedWidget(widget.id, {
														config: { ...widget.config, y_column: event.currentTarget.value }
													})}
												disabled={readOnly}
											/>
										</div>
										<div class={css({ display: 'grid', gap: '2', gridTemplateColumns: '1fr 1fr' })}>
											<select
												class={input()}
												value={String(widget.config.legend_position ?? 'right')}
												onchange={(event) =>
													updateSelectedWidget(widget.id, {
														config: {
															...widget.config,
															legend_position: event.currentTarget.value
														}
													})}
												disabled={readOnly}
											>
												<option value="top">legend top</option>
												<option value="right">legend right</option>
												<option value="bottom">legend bottom</option>
												<option value="left">legend left</option>
											</select>
											<label
												class={css({
													display: 'flex',
													alignItems: 'center',
													gap: '2',
													fontSize: 'xs',
													color: 'fg.secondary'
												})}
											>
												<input
													type="checkbox"
													checked={Boolean(widget.config.pan_zoom_enabled)}
													onchange={(event) =>
														updateSelectedWidget(widget.id, {
															config: {
																...widget.config,
																pan_zoom_enabled: event.currentTarget.checked
															}
														})}
													disabled={readOnly}
												/>
												Pan + zoom
											</label>
											<label
												class={css({
													display: 'flex',
													alignItems: 'center',
													gap: '2',
													fontSize: 'xs',
													color: 'fg.secondary'
												})}
											>
												<input
													type="checkbox"
													checked={Boolean(widget.config.selection_enabled)}
													onchange={(event) =>
														updateSelectedWidget(widget.id, {
															config: {
																...widget.config,
																selection_enabled: event.currentTarget.checked
															}
														})}
													disabled={readOnly}
												/>
												Click selection
											</label>
											<label
												class={css({
													display: 'flex',
													alignItems: 'center',
													gap: '2',
													fontSize: 'xs',
													color: 'fg.secondary'
												})}
											>
												<input
													type="checkbox"
													checked={Boolean(widget.config.area_selection_enabled)}
													onchange={(event) =>
														updateSelectedWidget(widget.id, {
															config: {
																...widget.config,
																area_selection_enabled: event.currentTarget.checked
															}
														})}
													disabled={readOnly}
												/>
												Area selection
											</label>
											<label
												class={css({
													display: 'flex',
													alignItems: 'center',
													gap: '2',
													fontSize: 'xs',
													color: 'fg.secondary'
												})}
											>
												<input
													type="checkbox"
													checked={Boolean(widget.config.selection_filters_widgets)}
													onchange={(event) =>
														updateSelectedWidget(widget.id, {
															config: {
																...widget.config,
																selection_filters_widgets: event.currentTarget.checked
															}
														})}
													disabled={readOnly}
												/>
												Filter sibling widgets
											</label>
										</div>
									</div>
								{:else if widget.type === 'metric_kpi'}
									<div
										class={css({ display: 'grid', gap: '2', gridTemplateColumns: '1fr 1fr 1fr' })}
									>
										<input
											class={input()}
											placeholder="Label"
											value={String(widget.config.label ?? '')}
											oninput={(event) =>
												updateSelectedWidget(widget.id, {
													config: { ...widget.config, label: event.currentTarget.value }
												})}
											disabled={readOnly}
										/>
										<select
											class={input()}
											value={String(widget.config.aggregation ?? 'count')}
											onchange={(event) =>
												updateSelectedWidget(widget.id, {
													config: { ...widget.config, aggregation: event.currentTarget.value }
												})}
											disabled={readOnly}
										>
											<option value="count">count</option>
											<option value="sum">sum</option>
											<option value="mean">mean</option>
											<option value="min">min</option>
											<option value="max">max</option>
											<option value="median">median</option>
											<option value="n_unique">n_unique</option>
										</select>
										<input
											class={input()}
											placeholder="Column"
											value={String(widget.config.column ?? '')}
											oninput={(event) =>
												updateSelectedWidget(widget.id, {
													config: { ...widget.config, column: event.currentTarget.value }
												})}
											disabled={readOnly}
										/>
									</div>
								{:else}
									<div class={css({ display: 'grid', gap: '2', gridTemplateColumns: '1fr auto' })}>
										<input
											class={input()}
											value={String(widget.config.text ?? '')}
											oninput={(event) =>
												updateSelectedWidget(widget.id, {
													config: { ...widget.config, text: event.currentTarget.value }
												})}
											disabled={readOnly}
										/>
										<select
											class={input()}
											value={String(widget.config.level ?? 2)}
											onchange={(event) =>
												updateSelectedWidget(widget.id, {
													config: { ...widget.config, level: Number(event.currentTarget.value) }
												})}
											disabled={readOnly}
										>
											<option value="1">H1</option>
											<option value="2">H2</option>
											<option value="3">H3</option>
										</select>
									</div>
								{/if}
								{#if layout}
									<div
										class={css({
											marginTop: '3',
											display: 'grid',
											gap: '2',
											gridTemplateColumns: 'repeat(4, 1fr)'
										})}
									>
										<input
											class={input()}
											type="number"
											min="0"
											value={String(layout.x)}
											oninput={(event) =>
												updateSelectedLayout(widget.id, { x: Number(event.currentTarget.value) })}
											disabled={readOnly}
										/>
										<input
											class={input()}
											type="number"
											min="0"
											value={String(layout.y)}
											oninput={(event) =>
												updateSelectedLayout(widget.id, { y: Number(event.currentTarget.value) })}
											disabled={readOnly}
										/>
										<input
											class={input()}
											type="number"
											min="1"
											max="12"
											value={String(layout.w)}
											oninput={(event) =>
												updateSelectedLayout(widget.id, { w: Number(event.currentTarget.value) })}
											disabled={readOnly}
										/>
										<input
											class={input()}
											type="number"
											min="1"
											max="8"
											value={String(layout.h)}
											oninput={(event) =>
												updateSelectedLayout(widget.id, { h: Number(event.currentTarget.value) })}
											disabled={readOnly}
										/>
									</div>
								{/if}
							</div>
						{/each}
					</div>
				</div>
			{/if}
		</section>
	</div>
</div>
