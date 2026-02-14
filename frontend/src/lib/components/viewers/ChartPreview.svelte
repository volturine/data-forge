<script lang="ts">
	import { Chart } from 'chart.js/auto';
	import type { ChartConfiguration, ChartDataset } from 'chart.js/auto';

	type ChartType = 'bar' | 'line' | 'pie' | 'histogram' | 'scatter' | 'boxplot';
	type Row = Record<string, unknown>;

	interface Props {
		data: Row[];
		chartType: ChartType;
		config: Record<string, unknown>;
	}

	const { data, chartType, config }: Props = $props();

	const PALETTE = [
		'#6366f1', // indigo
		'#f59e0b', // amber
		'#10b981', // emerald
		'#ef4444', // red
		'#8b5cf6', // violet
		'#06b6d4', // cyan
		'#f97316', // orange
		'#ec4899' // pink
	];

	const PALETTE_ALPHA = PALETTE.map((c) => c + '33');

	let canvas: HTMLCanvasElement | undefined = $state();

	function color(index: number): string {
		return PALETTE[index % PALETTE.length];
	}

	function colorAlpha(index: number): string {
		return PALETTE_ALPHA[index % PALETTE_ALPHA.length];
	}

	function asNumber(v: unknown): number {
		if (typeof v === 'number') return v;
		if (typeof v === 'string') return Number(v);
		return 0;
	}

	function asString(v: unknown): string {
		if (v == null) return '';
		return String(v);
	}

	function groupBy(rows: Row[], key: string): Map<string, Row[]> {
		// eslint-disable-next-line svelte/prefer-svelte-reactivity -- local non-reactive lookup in pure function
		const map = new Map<string, Row[]>();
		for (const row of rows) {
			const group = asString(row[key]);
			const arr = map.get(group);
			if (arr) {
				arr.push(row);
			} else {
				map.set(group, [row]);
			}
		}
		return map;
	}

	function buildBarOrLine(type: 'bar' | 'line'): ChartConfiguration {
		const groupCol = config.group_column as string | null;

		if (groupCol && data.length > 0 && groupCol in data[0]) {
			const groups = groupBy(data, groupCol);
			const labels = [...new Set(data.map((r) => asString(r.x)))];
			let idx = 0;
			const datasets: ChartDataset<typeof type>[] = [];

			for (const [name, rows] of groups) {
				const lookup = new Map(rows.map((r) => [asString(r.x), asNumber(r.y)]));
				datasets.push({
					label: name,
					data: labels.map((l) => lookup.get(l) ?? 0),
					backgroundColor: type === 'bar' ? color(idx) : colorAlpha(idx),
					borderColor: color(idx),
					borderWidth: type === 'line' ? 2 : 0,
					pointRadius: type === 'line' ? 0 : undefined,
					fill: type === 'line'
				} as ChartDataset<typeof type>);
				idx++;
			}

			return {
				type,
				data: { labels, datasets },
				options: chartOptions()
			};
		}

		const labels = data.map((r) => asString(r.x));
		const values = data.map((r) => asNumber(r.y));
		return {
			type,
			data: {
				labels,
				datasets: [
					{
						label: asString(config.y_column ?? 'y'),
						data: values,
						backgroundColor: type === 'bar' ? color(0) : colorAlpha(0),
						borderColor: color(0),
						borderWidth: type === 'line' ? 2 : 0,
						pointRadius: type === 'line' ? 0 : undefined,
						fill: type === 'line'
					}
				]
			},
			options: chartOptions()
		};
	}

	function buildPie(): ChartConfiguration {
		const labels = data.map((r) => asString(r.label));
		const values = data.map((r) => asNumber(r.y));
		return {
			type: 'pie',
			data: {
				labels,
				datasets: [
					{
						data: values,
						backgroundColor: data.map((_, i) => color(i)),
						borderWidth: 0
					}
				]
			},
			options: {
				...chartOptions(),
				scales: undefined
			}
		};
	}

	function buildHistogram(): ChartConfiguration {
		const labels = data.map((r) => {
			const start = asNumber(r.bin_start);
			const end = asNumber(r.bin_end);
			return `${start.toFixed(1)}–${end.toFixed(1)}`;
		});
		const values = data.map((r) => asNumber(r.count));
		return {
			type: 'bar',
			data: {
				labels,
				datasets: [
					{
						label: 'Count',
						data: values,
						backgroundColor: color(0),
						borderWidth: 0,
						barPercentage: 1.0,
						categoryPercentage: 1.0
					}
				]
			},
			options: chartOptions()
		};
	}

	function buildScatter(): ChartConfiguration {
		const groupCol = 'group';
		const hasGroup = data.length > 0 && groupCol in data[0];

		if (hasGroup) {
			const groups = groupBy(data, groupCol);
			let idx = 0;
			const datasets: ChartDataset<'scatter'>[] = [];

			for (const [name, rows] of groups) {
				datasets.push({
					label: name,
					data: rows.map((r) => ({ x: asNumber(r.x), y: asNumber(r.y) })),
					backgroundColor: colorAlpha(idx),
					borderColor: color(idx),
					borderWidth: 1,
					pointRadius: 3
				});
				idx++;
			}

			return {
				type: 'scatter',
				data: { datasets },
				options: chartOptions()
			};
		}

		return {
			type: 'scatter',
			data: {
				datasets: [
					{
						label: asString(config.y_column ?? 'y'),
						data: data.map((r) => ({ x: asNumber(r.x), y: asNumber(r.y) })),
						backgroundColor: colorAlpha(0),
						borderColor: color(0),
						borderWidth: 1,
						pointRadius: 3
					}
				]
			},
			options: chartOptions()
		};
	}

	function buildBoxplot(): ChartConfiguration {
		const groups = data.map((r) => asString(r.group));
		const whiskerColor = PALETTE[0] + '66';
		const boxColor = PALETTE[0];
		const boxColorLight = PALETTE[0] + 'aa';

		return {
			type: 'bar',
			data: {
				labels: groups,
				datasets: [
					{
						label: 'Min → Q1',
						data: data.map((r) => [asNumber(r.min), asNumber(r.q1)] as [number, number]),
						backgroundColor: whiskerColor,
						borderWidth: 0,
						barPercentage: 0.3
					},
					{
						label: 'Q1 → Median',
						data: data.map((r) => [asNumber(r.q1), asNumber(r.median)] as [number, number]),
						backgroundColor: boxColor,
						borderWidth: 0,
						barPercentage: 0.6
					},
					{
						label: 'Median → Q3',
						data: data.map((r) => [asNumber(r.median), asNumber(r.q3)] as [number, number]),
						backgroundColor: boxColorLight,
						borderWidth: 0,
						barPercentage: 0.6
					},
					{
						label: 'Q3 → Max',
						data: data.map((r) => [asNumber(r.q3), asNumber(r.max)] as [number, number]),
						backgroundColor: whiskerColor,
						borderWidth: 0,
						barPercentage: 0.3
					}
				]
			},
			options: {
				...chartOptions(),
				indexAxis: 'y',
				scales: {
					x: {
						stacked: false,
						grid: { color: 'var(--border-primary)' },
						ticks: { color: 'var(--fg-tertiary)', font: { size: 10 } }
					},
					y: {
						stacked: false,
						grid: { display: false },
						ticks: { color: 'var(--fg-tertiary)', font: { size: 10 } }
					}
				}
			}
		};
	}

	function chartOptions(): ChartConfiguration['options'] {
		return {
			responsive: true,
			maintainAspectRatio: false,
			animation: false,
			plugins: {
				legend: { display: false },
				title: { display: false },
				tooltip: {
					enabled: true,
					bodyFont: { size: 11 }
				}
			},
			scales: {
				x: {
					grid: { color: 'var(--border-primary)' },
					ticks: {
						color: 'var(--fg-tertiary)',
						font: { size: 10 },
						maxRotation: 45,
						autoSkip: true,
						maxTicksLimit: 20
					}
				},
				y: {
					grid: { color: 'var(--border-primary)' },
					ticks: {
						color: 'var(--fg-tertiary)',
						font: { size: 10 }
					}
				}
			},
			layout: {
				padding: { top: 4, right: 8, bottom: 4, left: 4 }
			}
		};
	}

	function buildConfig(): ChartConfiguration {
		switch (chartType) {
			case 'bar':
				return buildBarOrLine('bar');
			case 'line':
				return buildBarOrLine('line');
			case 'pie':
				return buildPie();
			case 'histogram':
				return buildHistogram();
			case 'scatter':
				return buildScatter();
			case 'boxplot':
				return buildBoxplot();
			default:
				return buildBarOrLine('bar');
		}
	}

	// $derived is not sufficient: Chart.js requires imperative canvas DOM access to create/destroy instances
	$effect(() => {
		if (!canvas || data.length === 0) return;

		const ctx = canvas.getContext('2d');
		if (!ctx) return;

		const chartConfig = buildConfig();
		const chart = new Chart(ctx, chartConfig);

		return () => {
			chart.destroy();
		};
	});
</script>

<div class="chart-container">
	{#if data.length === 0}
		<div class="chart-empty">
			<span>No data to display</span>
		</div>
	{:else}
		<canvas bind:this={canvas}></canvas>
	{/if}
</div>

<style>
	.chart-container {
		width: 100%;
		height: 200px;
		border: 1px solid var(--bg-tertiary);
		background-color: var(--bg-primary);
		overflow: hidden;
		contain: content;
	}

	.chart-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		color: var(--fg-muted);
		font-size: 0.75rem;
	}
</style>
