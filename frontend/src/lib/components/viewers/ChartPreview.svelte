<script lang="ts">
	import * as d3 from 'd3';

	type ChartType = 'bar' | 'line' | 'pie' | 'histogram' | 'scatter' | 'boxplot';
	type Row = Record<string, unknown>;

	interface Props {
		data: Row[];
		chartType: ChartType;
		config: Record<string, unknown>;
	}

	const { data, chartType, config }: Props = $props();

	const PALETTE = [
		'#6366f1',
		'#f59e0b',
		'#10b981',
		'#ef4444',
		'#8b5cf6',
		'#06b6d4',
		'#f97316',
		'#ec4899'
	];

	let container: HTMLDivElement | undefined = $state();

	function num(v: unknown): number {
		if (typeof v === 'number') return v;
		if (typeof v === 'string') return Number(v) || 0;
		return 0;
	}

	function str(v: unknown): string {
		if (v == null) return '';
		return String(v);
	}

	function fmt(v: number): string {
		if (Math.abs(v) >= 1e6) return d3.format('.2s')(v);
		if (Math.abs(v) >= 1e3) return d3.format(',.0f')(v);
		if (Number.isInteger(v)) return String(v);
		return d3.format('.2f')(v);
	}

	// $derived is not sufficient: D3 requires imperative DOM access to render SVG
	$effect(() => {
		if (!container || data.length === 0) return;

		// Clear previous render
		d3.select(container).selectAll('*').remove();

		const rect = container.getBoundingClientRect();
		const width = rect.width || 300;
		const height = rect.height || 200;

		switch (chartType) {
			case 'bar':
				renderBar(container, width, height);
				break;
			case 'line':
				renderLine(container, width, height);
				break;
			case 'pie':
				renderPie(container, width, height);
				break;
			case 'histogram':
				renderHistogram(container, width, height);
				break;
			case 'scatter':
				renderScatter(container, width, height);
				break;
			case 'boxplot':
				renderBoxplot(container, width, height);
				break;
			default:
				renderBar(container, width, height);
		}

		return () => {
			if (container) d3.select(container).selectAll('*').remove();
		};
	});

	function renderBar(el: HTMLDivElement, width: number, height: number) {
		const margin = { top: 8, right: 8, bottom: 32, left: 44 };
		const w = width - margin.left - margin.right;
		const h = height - margin.top - margin.bottom;

		const svg = d3
			.select(el)
			.append('svg')
			.attr('width', width)
			.attr('height', height)
			.append('g')
			.attr('transform', `translate(${margin.left},${margin.top})`);

		const groupCol = config.group_column as string | null;
		const hasGroup = groupCol && data.length > 0 && groupCol in data[0];

		if (hasGroup) {
			const labels = [...new Set(data.map((r) => str(r.x)))];
			const groups = [...new Set(data.map((r) => str(r[groupCol])))];
			const color = d3.scaleOrdinal<string>().domain(groups).range(PALETTE);

			const x0 = d3.scaleBand().domain(labels).range([0, w]).padding(0.2);
			const x1 = d3.scaleBand().domain(groups).range([0, x0.bandwidth()]).padding(0.05);
			const y = d3
				.scaleLinear()
				.domain([0, d3.max(data, (r) => num(r.y)) ?? 0])
				.nice()
				.range([h, 0]);

			svg
				.append('g')
				.attr('transform', `translate(0,${h})`)
				.call(
					d3
						.axisBottom(x0)
						.tickSizeOuter(0)
						.tickFormat((d) => (d.length > 8 ? d.slice(0, 8) + '..' : d))
				)
				.selectAll('text')
				.attr('fill', 'var(--fg-tertiary)')
				.style('font-size', '9px');

			svg
				.append('g')
				.call(
					d3
						.axisLeft(y)
						.ticks(5)
						.tickFormat((d) => fmt(d as number))
				)
				.selectAll('text')
				.attr('fill', 'var(--fg-tertiary)')
				.style('font-size', '9px');

			for (const group of groups) {
				const rows = data.filter((r) => str(r[groupCol]) === group);
				svg
					.selectAll(`.bar-${group}`)
					.data(rows)
					.join('rect')
					.attr('x', (r) => (x0(str(r.x)) ?? 0) + (x1(group) ?? 0))
					.attr('y', (r) => y(num(r.y)))
					.attr('width', x1.bandwidth())
					.attr('height', (r) => h - y(num(r.y)))
					.attr('fill', color(group))
					.attr('rx', 1);
			}
		} else {
			const labels = data.map((r) => str(r.x));
			const x = d3.scaleBand().domain(labels).range([0, w]).padding(0.3);
			const y = d3
				.scaleLinear()
				.domain([0, d3.max(data, (r) => num(r.y)) ?? 0])
				.nice()
				.range([h, 0]);

			svg
				.append('g')
				.attr('transform', `translate(0,${h})`)
				.call(
					d3
						.axisBottom(x)
						.tickSizeOuter(0)
						.tickFormat((d) => (d.length > 8 ? d.slice(0, 8) + '..' : d))
				)
				.selectAll('text')
				.attr('fill', 'var(--fg-tertiary)')
				.style('font-size', '9px');

			svg
				.append('g')
				.call(
					d3
						.axisLeft(y)
						.ticks(5)
						.tickFormat((d) => fmt(d as number))
				)
				.selectAll('text')
				.attr('fill', 'var(--fg-tertiary)')
				.style('font-size', '9px');

			svg
				.selectAll('.bar')
				.data(data)
				.join('rect')
				.attr('x', (r) => x(str(r.x)) ?? 0)
				.attr('y', (r) => y(num(r.y)))
				.attr('width', x.bandwidth())
				.attr('height', (r) => h - y(num(r.y)))
				.attr('fill', PALETTE[0])
				.attr('rx', 2);
		}

		styleAxes(svg);
	}

	function renderLine(el: HTMLDivElement, width: number, height: number) {
		const margin = { top: 8, right: 8, bottom: 32, left: 44 };
		const w = width - margin.left - margin.right;
		const h = height - margin.top - margin.bottom;

		const svg = d3
			.select(el)
			.append('svg')
			.attr('width', width)
			.attr('height', height)
			.append('g')
			.attr('transform', `translate(${margin.left},${margin.top})`);

		const groupCol = config.group_column as string | null;
		const hasGroup = groupCol && data.length > 0 && groupCol in data[0];
		const labels = [...new Set(data.map((r) => str(r.x)))];

		const x = d3.scalePoint().domain(labels).range([0, w]).padding(0.5);
		const y = d3
			.scaleLinear()
			.domain([0, d3.max(data, (r) => num(r.y)) ?? 0])
			.nice()
			.range([h, 0]);

		svg
			.append('g')
			.attr('transform', `translate(0,${h})`)
			.call(
				d3
					.axisBottom(x)
					.tickSizeOuter(0)
					.tickFormat((d) => (d.length > 8 ? d.slice(0, 8) + '..' : d))
			)
			.selectAll('text')
			.attr('fill', 'var(--fg-tertiary)')
			.style('font-size', '9px');

		svg
			.append('g')
			.call(
				d3
					.axisLeft(y)
					.ticks(5)
					.tickFormat((d) => fmt(d as number))
			)
			.selectAll('text')
			.attr('fill', 'var(--fg-tertiary)')
			.style('font-size', '9px');

		if (hasGroup) {
			const groups = [...new Set(data.map((r) => str(r[groupCol])))];
			const color = d3.scaleOrdinal<string>().domain(groups).range(PALETTE);

			for (const group of groups) {
				const rows = data
					.filter((r) => str(r[groupCol]) === group)
					.sort((a, b) => {
						const ai = labels.indexOf(str(a.x));
						const bi = labels.indexOf(str(b.x));
						return ai - bi;
					});

				const line = d3
					.line<Row>()
					.x((r) => x(str(r.x)) ?? 0)
					.y((r) => y(num(r.y)))
					.curve(d3.curveMonotoneX);

				// Area fill
				const area = d3
					.area<Row>()
					.x((r) => x(str(r.x)) ?? 0)
					.y0(h)
					.y1((r) => y(num(r.y)))
					.curve(d3.curveMonotoneX);

				svg
					.append('path')
					.datum(rows)
					.attr('d', area)
					.attr('fill', color(group))
					.attr('opacity', 0.1);
				svg
					.append('path')
					.datum(rows)
					.attr('d', line)
					.attr('fill', 'none')
					.attr('stroke', color(group))
					.attr('stroke-width', 2);
			}
		} else {
			const sorted = [...data].sort((a, b) => labels.indexOf(str(a.x)) - labels.indexOf(str(b.x)));

			const line = d3
				.line<Row>()
				.x((r) => x(str(r.x)) ?? 0)
				.y((r) => y(num(r.y)))
				.curve(d3.curveMonotoneX);

			const area = d3
				.area<Row>()
				.x((r) => x(str(r.x)) ?? 0)
				.y0(h)
				.y1((r) => y(num(r.y)))
				.curve(d3.curveMonotoneX);

			svg
				.append('path')
				.datum(sorted)
				.attr('d', area)
				.attr('fill', PALETTE[0])
				.attr('opacity', 0.1);
			svg
				.append('path')
				.datum(sorted)
				.attr('d', line)
				.attr('fill', 'none')
				.attr('stroke', PALETTE[0])
				.attr('stroke-width', 2);
		}

		styleAxes(svg);
	}

	function renderPie(el: HTMLDivElement, width: number, height: number) {
		const radius = Math.min(width, height) / 2 - 8;

		const svg = d3
			.select(el)
			.append('svg')
			.attr('width', width)
			.attr('height', height)
			.append('g')
			.attr('transform', `translate(${width / 2},${height / 2})`);

		const values = data.map((r) => num(r.y));
		const labels = data.map((r) => str(r.label));
		const color = d3.scaleOrdinal<number, string>().domain(d3.range(values.length)).range(PALETTE);

		const pie = d3.pie<number>().sort(null);
		const arc = d3
			.arc<d3.PieArcDatum<number>>()
			.innerRadius(radius * 0.4)
			.outerRadius(radius);

		const arcs = svg.selectAll('.arc').data(pie(values)).join('g').attr('class', 'arc');

		arcs
			.append('path')
			.attr('d', arc)
			.attr('fill', (_, i) => color(i))
			.attr('stroke', 'var(--bg-primary)')
			.attr('stroke-width', 1);

		// Labels for larger slices
		const total = d3.sum(values);
		const labelArc = d3
			.arc<d3.PieArcDatum<number>>()
			.innerRadius(radius * 0.65)
			.outerRadius(radius * 0.65);

		arcs
			.filter((d) => (d.endAngle - d.startAngle) / (2 * Math.PI) > 0.08)
			.append('text')
			.attr('transform', (d) => `translate(${labelArc.centroid(d)})`)
			.attr('text-anchor', 'middle')
			.attr('dominant-baseline', 'central')
			.attr('fill', 'var(--fg-primary)')
			.style('font-size', '9px')
			.text((_, i) => {
				const pct = ((values[i] / total) * 100).toFixed(0);
				const lbl = labels[i].length > 6 ? labels[i].slice(0, 6) + '..' : labels[i];
				return `${lbl} ${pct}%`;
			});
	}

	function renderHistogram(el: HTMLDivElement, width: number, height: number) {
		const margin = { top: 8, right: 8, bottom: 32, left: 44 };
		const w = width - margin.left - margin.right;
		const h = height - margin.top - margin.bottom;

		const svg = d3
			.select(el)
			.append('svg')
			.attr('width', width)
			.attr('height', height)
			.append('g')
			.attr('transform', `translate(${margin.left},${margin.top})`);

		const xMin = d3.min(data, (r) => num(r.bin_start)) ?? 0;
		const xMax = d3.max(data, (r) => num(r.bin_end)) ?? 1;
		const x = d3.scaleLinear().domain([xMin, xMax]).range([0, w]);
		const y = d3
			.scaleLinear()
			.domain([0, d3.max(data, (r) => num(r.count)) ?? 0])
			.nice()
			.range([h, 0]);

		svg
			.append('g')
			.attr('transform', `translate(0,${h})`)
			.call(
				d3
					.axisBottom(x)
					.ticks(6)
					.tickFormat((d) => fmt(d as number))
			)
			.selectAll('text')
			.attr('fill', 'var(--fg-tertiary)')
			.style('font-size', '9px');

		svg
			.append('g')
			.call(
				d3
					.axisLeft(y)
					.ticks(5)
					.tickFormat((d) => fmt(d as number))
			)
			.selectAll('text')
			.attr('fill', 'var(--fg-tertiary)')
			.style('font-size', '9px');

		svg
			.selectAll('.bin')
			.data(data)
			.join('rect')
			.attr('x', (r) => x(num(r.bin_start)))
			.attr('y', (r) => y(num(r.count)))
			.attr('width', (r) => Math.max(0, x(num(r.bin_end)) - x(num(r.bin_start)) - 1))
			.attr('height', (r) => h - y(num(r.count)))
			.attr('fill', PALETTE[0])
			.attr('rx', 1);

		styleAxes(svg);
	}

	function renderScatter(el: HTMLDivElement, width: number, height: number) {
		const margin = { top: 8, right: 8, bottom: 32, left: 44 };
		const w = width - margin.left - margin.right;
		const h = height - margin.top - margin.bottom;

		const svg = d3
			.select(el)
			.append('svg')
			.attr('width', width)
			.attr('height', height)
			.append('g')
			.attr('transform', `translate(${margin.left},${margin.top})`);

		const xExtent = d3.extent(data, (r) => num(r.x)) as [number, number];
		const yExtent = d3.extent(data, (r) => num(r.y)) as [number, number];
		const x = d3.scaleLinear().domain(xExtent).nice().range([0, w]);
		const y = d3.scaleLinear().domain(yExtent).nice().range([h, 0]);

		svg
			.append('g')
			.attr('transform', `translate(0,${h})`)
			.call(
				d3
					.axisBottom(x)
					.ticks(6)
					.tickFormat((d) => fmt(d as number))
			)
			.selectAll('text')
			.attr('fill', 'var(--fg-tertiary)')
			.style('font-size', '9px');

		svg
			.append('g')
			.call(
				d3
					.axisLeft(y)
					.ticks(5)
					.tickFormat((d) => fmt(d as number))
			)
			.selectAll('text')
			.attr('fill', 'var(--fg-tertiary)')
			.style('font-size', '9px');

		const hasGroup = data.length > 0 && 'group' in data[0];

		if (hasGroup) {
			const groups = [...new Set(data.map((r) => str(r.group)))];
			const color = d3.scaleOrdinal<string>().domain(groups).range(PALETTE);

			svg
				.selectAll('.dot')
				.data(data)
				.join('circle')
				.attr('cx', (r) => x(num(r.x)))
				.attr('cy', (r) => y(num(r.y)))
				.attr('r', 2.5)
				.attr('fill', (r) => color(str(r.group)))
				.attr('opacity', 0.7);
		} else {
			svg
				.selectAll('.dot')
				.data(data)
				.join('circle')
				.attr('cx', (r) => x(num(r.x)))
				.attr('cy', (r) => y(num(r.y)))
				.attr('r', 2.5)
				.attr('fill', PALETTE[0])
				.attr('opacity', 0.7);
		}

		styleAxes(svg);
	}

	function renderBoxplot(el: HTMLDivElement, width: number, height: number) {
		const margin = { top: 8, right: 8, bottom: 8, left: 44 };
		const w = width - margin.left - margin.right;
		const h = height - margin.top - margin.bottom;

		const svg = d3
			.select(el)
			.append('svg')
			.attr('width', width)
			.attr('height', height)
			.append('g')
			.attr('transform', `translate(${margin.left},${margin.top})`);

		const groups = data.map((r) => str(r.group));
		const y = d3.scaleBand().domain(groups).range([0, h]).padding(0.3);

		const xMin = d3.min(data, (r) => num(r.min)) ?? 0;
		const xMax = d3.max(data, (r) => num(r.max)) ?? 1;
		const x = d3.scaleLinear().domain([xMin, xMax]).nice().range([0, w]);

		svg
			.append('g')
			.call(d3.axisLeft(y).tickSizeOuter(0))
			.selectAll('text')
			.attr('fill', 'var(--fg-tertiary)')
			.style('font-size', '9px');

		svg
			.append('g')
			.attr('transform', `translate(0,${h})`)
			.call(
				d3
					.axisBottom(x)
					.ticks(6)
					.tickFormat((d) => fmt(d as number))
			)
			.selectAll('text')
			.attr('fill', 'var(--fg-tertiary)')
			.style('font-size', '9px');

		const bandH = y.bandwidth();

		for (const row of data) {
			const g = str(row.group);
			const cy = (y(g) ?? 0) + bandH / 2;

			// Whisker line (min to max)
			svg
				.append('line')
				.attr('x1', x(num(row.min)))
				.attr('x2', x(num(row.max)))
				.attr('y1', cy)
				.attr('y2', cy)
				.attr('stroke', PALETTE[0])
				.attr('stroke-width', 1);

			// Box (Q1 to Q3)
			const q1x = x(num(row.q1));
			const q3x = x(num(row.q3));
			svg
				.append('rect')
				.attr('x', q1x)
				.attr('y', cy - bandH * 0.35)
				.attr('width', Math.max(0, q3x - q1x))
				.attr('height', bandH * 0.7)
				.attr('fill', PALETTE[0])
				.attr('opacity', 0.3)
				.attr('stroke', PALETTE[0])
				.attr('stroke-width', 1)
				.attr('rx', 2);

			// Median line
			svg
				.append('line')
				.attr('x1', x(num(row.median)))
				.attr('x2', x(num(row.median)))
				.attr('y1', cy - bandH * 0.35)
				.attr('y2', cy + bandH * 0.35)
				.attr('stroke', PALETTE[0])
				.attr('stroke-width', 2);

			// Min/Max whisker caps
			for (const val of [num(row.min), num(row.max)]) {
				svg
					.append('line')
					.attr('x1', x(val))
					.attr('x2', x(val))
					.attr('y1', cy - bandH * 0.2)
					.attr('y2', cy + bandH * 0.2)
					.attr('stroke', PALETTE[0])
					.attr('stroke-width', 1);
			}
		}

		styleAxes(svg);
	}

	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	function styleAxes(svg: d3.Selection<SVGGElement, unknown, null, any>) {
		svg.selectAll('.domain').attr('stroke', 'var(--border-primary)');
		svg.selectAll('.tick line').attr('stroke', 'var(--border-primary)');
	}
</script>

<div class="chart-container" bind:this={container}>
	{#if data.length === 0}
		<div class="chart-empty">
			<span>No data to display</span>
		</div>
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
