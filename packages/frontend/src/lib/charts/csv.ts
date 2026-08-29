import { readNumber, readString, type ChartConfig } from './format';
import { stringValue, type ChartRow } from './preparation';

type CsvRow = { dataset: string; x: string; y: string };

function csvEscape(value: string): string {
	const escaped = value.replaceAll('"', '""');
	const needsQuotes = escaped.includes(',') || escaped.includes('\n') || escaped.includes('"');
	if (!needsQuotes) return escaped;
	return `"${escaped}"`;
}

function overlayMarksOf(metadata: Record<string, unknown> | null | undefined): ChartRow[] {
	const raw = metadata?.overlays;
	if (!Array.isArray(raw)) return [];
	return raw.filter((item) => item && typeof item === 'object') as ChartRow[];
}

function overlaySeriesLabel(overlay: ChartRow): string {
	const yCol = readString(overlay, 'y_column');
	const agg = readString(overlay, 'aggregation');
	if (!yCol) return 'Overlay';
	if (!agg) return yCol;
	return `${agg.charAt(0).toUpperCase()}${agg.slice(1)} of ${yCol}`;
}

function referenceLinesOf(metadata: Record<string, unknown> | null | undefined): ChartRow[] {
	const raw = metadata?.reference_lines;
	if (!Array.isArray(raw)) return [];
	return raw.filter((item) => item && typeof item === 'object') as ChartRow[];
}

function buildRows(data: ChartRow[], chartType: string, config: ChartConfig): CsvRow[] {
	const title = readString(config, 'title').trim();
	const fallback = title || 'Primary';
	if (chartType === 'histogram') {
		return data.map((row) => ({
			dataset: fallback,
			x: stringValue(row.bin_start),
			y: stringValue(row.count)
		}));
	}
	if (chartType === 'heatgrid') {
		return data.map((row) => ({
			dataset: stringValue(row.y) || fallback,
			x: stringValue(row.x),
			y: stringValue(row.value)
		}));
	}
	if (chartType === 'boxplot') {
		const rows: CsvRow[] = [];
		for (const row of data) {
			const dataset = stringValue(row.group) || fallback;
			const stats: Array<[string, unknown]> = [
				['min', row.min],
				['q1', row.q1],
				['median', row.median],
				['q3', row.q3],
				['max', row.max]
			];
			for (const stat of stats) {
				rows.push({ dataset, x: stat[0], y: stringValue(stat[1]) });
			}
		}
		return rows;
	}
	if (chartType === 'pie') {
		return data.map((row) => ({
			dataset: stringValue(row.group) || fallback,
			x: stringValue(row.label ?? row.x),
			y: stringValue(row.y ?? row.value ?? row.count)
		}));
	}
	const groupCol = readString(config, 'group_column');
	return data.map((row) => {
		const dataset =
			groupCol && row[groupCol] != null
				? stringValue(row[groupCol])
				: row['group'] != null
					? stringValue(row['group'])
					: fallback;
		return {
			dataset,
			x: stringValue(row.x ?? row.label),
			y: stringValue(row.y ?? row.value ?? row.count)
		};
	});
}

export function chartCsv(
	data: ChartRow[],
	chartType: string,
	config: ChartConfig,
	metadata?: Record<string, unknown> | null
): string {
	const rows: CsvRow[] = [...buildRows(data, chartType, config)];
	for (const overlay of overlayMarksOf(metadata ?? null)) {
		const label = overlaySeriesLabel(overlay);
		const raw = overlay.data;
		if (!Array.isArray(raw)) continue;
		for (const point of raw as ChartRow[]) {
			rows.push({
				dataset: label,
				x: stringValue(point.x ?? point.label),
				y: stringValue(point.y ?? point.value ?? point.count)
			});
		}
	}
	for (const line of referenceLinesOf(metadata ?? null)) {
		const value = readNumber(line, 'value');
		if (value == null) continue;
		const axis = readString(line, 'axis') || readString(line, 'target_axis') || 'y';
		const position = readString(line, 'y_axis_position') || readString(line, 'target_axis');
		const baseLabel = readString(line, 'label').trim();
		const suffix = position === 'right' && axis === 'y' ? ' right' : '';
		const dataset = baseLabel || `Reference ${axis.toUpperCase()}${suffix}`;
		if (axis === 'x') {
			rows.push({ dataset, x: String(value), y: '' });
		} else {
			rows.push({ dataset, x: '', y: String(value) });
		}
	}
	const header = 'dataset,x,y';
	const body = rows.map((row) => [row.dataset, row.x, row.y].map(csvEscape).join(',')).join('\n');
	return [header, body].filter((line) => line.length > 0).join('\n');
}
