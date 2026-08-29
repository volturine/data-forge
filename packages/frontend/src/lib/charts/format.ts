import { formatEpoch, parsePlainDateTime } from '$lib/utils/temporal';
import { stringValue, type ChartRow } from './preparation';

export type ChartConfig = Record<string, unknown>;
export type ChartType =
	| 'bar'
	| 'horizontal_bar'
	| 'area'
	| 'heatgrid'
	| 'line'
	| 'pie'
	| 'histogram'
	| 'scatter'
	| 'boxplot';

export const CHART_PALETTE = [
	'var(--colors-indigo-500)',
	'var(--colors-emerald-500)',
	'var(--colors-amber-500)',
	'var(--colors-rose-500)',
	'var(--colors-violet-500)',
	'var(--colors-teal-500)',
	'var(--colors-orange-500)',
	'var(--colors-purple-400)'
];

export const CHART_THEME = {
	foreground: 'var(--colors-fg-primary)',
	muted: 'var(--colors-fg-tertiary)',
	grid: 'var(--colors-border-primary)',
	background: 'transparent'
} as const;

export const FG_MUTED = 'var(--colors-fg-muted)';
export const FG_SECONDARY = 'var(--colors-fg-secondary)';

export function readString(config: ChartConfig, key: string): string {
	return stringValue(config[key]);
}

export function readNumber(config: ChartConfig, key: string): number | null {
	const value = config[key];
	if (value == null) return null;
	const parsed = Number(value);
	return Number.isNaN(parsed) ? null : parsed;
}

export function decimalPlaces(config: ChartConfig): number {
	const raw = readNumber(config, 'decimal_places') ?? 2;
	if (raw < 0) return 0;
	if (raw > 6) return 6;
	return Math.round(raw);
}

function applyUnits(v: number, config: ChartConfig): { value: number; suffix: string } {
	const unit = readString(config, 'display_units');
	if (unit === 'K') return { value: v / 1e3, suffix: 'K' };
	if (unit === 'M') return { value: v / 1e6, suffix: 'M' };
	if (unit === 'B') return { value: v / 1e9, suffix: 'B' };
	if (unit === '%') return { value: v * 100, suffix: '%' };
	return { value: v, suffix: '' };
}

export function formatNumber(v: number, config: ChartConfig): string {
	const decimals = decimalPlaces(config);
	const formatted = applyUnits(v, config);
	const text = new Intl.NumberFormat('en-US', {
		minimumFractionDigits: decimals,
		maximumFractionDigits: decimals
	}).format(formatted.value);
	return `${text}${formatted.suffix}`;
}

export function formatTimeTick(value: unknown, config: ChartConfig): string {
	const raw = stringValue(value);
	if (!raw) return '';
	const parsed = parsePlainDateTime(raw);
	if (!parsed) return raw;
	const bucket = readString(config, 'date_bucket');
	const ordinal = readString(config, 'date_ordinal');
	const quarter = Math.floor((parsed.month - 1) / 3) + 1;
	const epochMs = parsed
		.toPlainDate()
		.toZonedDateTime({ timeZone: 'UTC', plainTime: { hour: parsed.hour, minute: parsed.minute } })
		.toInstant().epochMilliseconds;
	if (ordinal === 'day_of_week') return formatEpoch(epochMs, { weekday: 'short' }, 'UTC');
	if (ordinal === 'month_of_year') return formatEpoch(epochMs, { month: 'short' }, 'UTC');
	if (ordinal === 'quarter_of_year') return `Q${quarter}`;
	if (bucket === 'year') return String(parsed.year);
	if (bucket === 'quarter') return `Q${quarter} ${parsed.year}`;
	if (bucket === 'month') return formatEpoch(epochMs, { month: 'short', year: 'numeric' }, 'UTC');
	if (bucket === 'week') return formatEpoch(epochMs, { month: 'short', day: '2-digit' }, 'UTC');
	if (bucket === 'day') return formatEpoch(epochMs, { month: 'short', day: '2-digit' }, 'UTC');
	if (bucket === 'hour') {
		return `${formatEpoch(epochMs, { month: 'short', day: '2-digit' }, 'UTC')} ${String(parsed.hour).padStart(2, '0')}:00`;
	}
	return parsed.toPlainDate().toString();
}

export function xAxisTitle(config: ChartConfig): string {
	const label = readString(config, 'x_axis_label').trim();
	if (label) return label;
	return readString(config, 'x_column') || 'Category';
}

export function yAxisTitle(config: ChartConfig, chartType: ChartType): string {
	const label = readString(config, 'y_axis_label').trim();
	if (label) return label;
	const agg = readString(config, 'aggregation');
	const col = readString(config, 'y_column');
	if (chartType === 'histogram') return 'Count';
	if (chartType === 'heatgrid' || chartType === 'scatter' || chartType === 'boxplot') {
		return col || 'Value';
	}
	if (!col) return 'Count';
	return `${agg.charAt(0).toUpperCase()}${agg.slice(1)} of ${col}`;
}

export function seriesColors(config: ChartConfig): string[] {
	const raw = config.series_colors;
	if (!Array.isArray(raw)) return [...CHART_PALETTE];
	const cleaned = raw.map((value) => stringValue(value).trim()).filter((value) => value.length > 0);
	if (cleaned.length === 0) return [...CHART_PALETTE];
	return cleaned;
}

export function stackMode(config: ChartConfig): 'grouped' | 'stacked' | '100%' {
	const raw = readString(config, 'stack_mode');
	if (raw === 'stacked' || raw === '100%') return raw;
	return 'grouped';
}

export function groupSort(config: ChartConfig): {
	mode: 'name' | 'value' | 'custom' | null;
	order: 'asc' | 'desc';
	customColumn: string;
} {
	const raw = readString(config, 'group_sort_by');
	return {
		mode: raw === 'name' || raw === 'value' || raw === 'custom' ? raw : null,
		order: readString(config, 'group_sort_order') === 'desc' ? 'desc' : 'asc',
		customColumn: readString(config, 'group_sort_column')
	};
}

export function areaOpacity(config: ChartConfig): number {
	const raw = readNumber(config, 'area_opacity') ?? 0.35;
	return Math.max(0, Math.min(1, raw));
}

export function needsRotatedTicks(labels: string[]): boolean {
	const maxLen = Math.max(0, ...labels.map((label) => label.length));
	return maxLen > 8 && labels.length > 4;
}

export function truncateLabel(text: string, maxChars: number): string {
	if (text.length <= maxChars) return text;
	return text.slice(0, maxChars - 1) + '…';
}

export function overlayRowsOf(metadata: Record<string, unknown> | null | undefined): ChartRow[] {
	const raw = metadata?.overlays;
	if (!Array.isArray(raw)) return [];
	return raw.filter((item) => item && typeof item === 'object') as ChartRow[];
}

export function referenceLinesOf(metadata: Record<string, unknown> | null | undefined): ChartRow[] {
	const raw = metadata?.reference_lines;
	if (!Array.isArray(raw)) return [];
	return raw.filter((item) => item && typeof item === 'object') as ChartRow[];
}
