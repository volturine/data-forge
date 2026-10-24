import {
	ArrowUpDown,
	ChartColumn,
	ChartColumnIncreasing,
	Bomb,
	Brush,
	Calculator,
	Calendar,
	Dices,
	Download,
	Eye,
	Funnel,
	LayoutGrid,
	Link,
	Pencil,
	Repeat,
	Repeat2,
	Scissors,
	Settings2,
	Sparkles,
	Trophy,
	Type,
	Upload,
	Wrench,
	ListChecks,
	Trash2,
	Bell
} from '@lucide/svelte';
import {
	isChartStepType,
	normalizePipelineStepType,
	type CanonicalStepType
} from '#lib/types/pipeline-step.js';

function truncate(items: string[], max = 3, len = 20): string {
	if (!items?.length) return '';
	const shown = items
		.slice(0, max)
		.map((item) => (item.length > len ? item.slice(0, len - 1) + '…' : item));
	return items.length > max ? `${shown.join(', ')} +${items.length - max}` : shown.join(', ');
}

type StepTypeConfig = {
	label: string;
	icon: typeof Funnel;
	summary: (c: Record<string, unknown>) => string;
};

const stepTypes = {
	filter: {
		label: 'Filter',
		icon: Funnel,
		summary: (c) => {
			const conds = c.conditions as Array<{ column: string; operator: string; value: string }>;
			const logic = (c.logic as string) || 'AND';
			if (!conds?.length) return 'no conditions';
			if (conds.length <= 2) {
				return conds.map((x) => `${x.column} ${x.operator} ${x.value}`).join(` ${logic} `);
			}
			return `${conds.length} conditions (${logic})`;
		}
	},
	select: {
		label: 'Select',
		icon: ListChecks,
		summary: (c) => {
			const cols = c.columns as string[];
			return cols?.length ? truncate(cols) : 'no columns';
		}
	},
	groupby: {
		label: 'Group By',
		icon: ChartColumn,
		summary: (c) => {
			const keys = c.group_by as string[];
			const aggs = c.aggregations as Array<{ column: string; function: string }>;
			if (!keys?.length) return 'not configured';
			const aggStr =
				aggs
					?.slice(0, 2)
					.map((a) => `${a.function}(${a.column})`)
					.join(', ') || '';
			const extra = aggs?.length > 2 ? ` +${aggs.length - 2}` : '';
			return `by ${truncate(keys, 2)} → ${aggStr}${extra}`;
		}
	},
	sort: {
		label: 'Sort',
		icon: ArrowUpDown,
		summary: (c) => {
			const cols = c.columns as string[];
			const desc = c.descending as boolean[];
			if (!cols?.length) return 'not configured';
			return cols.map((col, i) => `${col} ${desc?.[i] ? '▼' : '▲'}`).join(', ');
		}
	},
	rename: {
		label: 'Rename',
		icon: Pencil,
		summary: (c) => {
			const map = c.column_mapping as Record<string, string>;
			const entries = Object.entries(map || {});
			if (!entries.length) return 'no renames';
			if (entries.length <= 2) return entries.map(([o, n]) => `${o} → ${n}`).join(', ');
			return `${entries.length} columns renamed`;
		}
	},
	drop: {
		label: 'Drop',
		icon: Trash2,
		summary: (c) => {
			const cols = c.columns as string[];
			return cols?.length ? truncate(cols) : 'no columns';
		}
	},
	join: {
		label: 'Join',
		icon: Link,
		summary: (c) => {
			const how = (c.how as string) || 'inner';
			const joins = c.join_columns as Array<{ left_column: string }>;
			const suffix = c.suffix as string;
			if (!joins?.length) return `${how} join (no keys)`;
			const base = `${how} on ${joins.map((j) => j.left_column).join(', ')}`;
			return suffix ? `${base}, suffix: ${suffix}` : base;
		}
	},
	expression: {
		label: 'Expression',
		icon: Calculator,
		summary: (c) => {
			const expr = c.expression as string;
			const col = c.column_name as string;
			if (!expr) return 'no expression';
			const short = expr.length > 25 ? expr.slice(0, 24) + '…' : expr;
			return `${col} = ${short}`;
		}
	},
	with_columns: {
		label: 'With Columns',
		icon: Calculator,
		summary: (c) => {
			const expressions = c.expressions as Array<{ name?: string }>;
			if (!expressions?.length) return 'no columns';
			const names = expressions
				.map((expr) => (typeof expr.name === 'string' ? expr.name : ''))
				.filter((name) => !!name);
			if (!names.length) return `${expressions.length} columns`;
			return names.length === 1 ? names[0] : `${truncate(names, 2)} (${names.length})`;
		}
	},
	pivot: {
		label: 'Pivot',
		icon: Repeat,
		summary: (c) => {
			const col = c.columns as string;
			const vals = Array.isArray(c.value_columns) ? (c.value_columns as string[]) : [];
			const agg = c.aggregate_function as string;
			const idx = c.index as string[];
			if (!col || !idx?.length) return 'not configured';
			const valuesLabel = vals.length ? truncate(vals, 2, 15) : 'all remaining columns';
			const base = `${col} → ${agg}(${valuesLabel})`;
			return idx?.length ? `${base}, index: ${truncate(idx, 2, 15)}` : base;
		}
	},
	unpivot: {
		label: 'Unpivot',
		icon: Repeat2,
		summary: (c) => {
			const valueVars = c.value_vars as string[] | undefined;
			const varName = (c.variable_name as string) || 'variable';
			const valName = (c.value_name as string) || 'value';
			if (!valueVars?.length) return 'not configured';
			return `${truncate(valueVars, 2)} → (${varName}, ${valName})`;
		}
	},
	fill_null: {
		label: 'Fill Null',
		icon: Wrench,
		summary: (c) => {
			const strategy = (c.strategy as string) || 'literal';
			const cols = c.columns as string[] | null;
			const value = c.value;
			const colPart = cols?.length ? truncate(cols, 2) : 'all';
			if (strategy === 'literal' && value !== undefined) return `${colPart} → ${value}`;
			return `${colPart}: ${strategy}`;
		}
	},
	deduplicate: {
		label: 'Deduplicate',
		icon: Brush,
		summary: (c) => {
			const subset = c.subset as string[] | null;
			const keep = (c.keep as string) || 'first';
			if (!subset?.length) return `all cols, keep ${keep}`;
			return `${truncate(subset, 2)}, keep ${keep}`;
		}
	},
	explode: {
		label: 'Explode',
		icon: Bomb,
		summary: (c) => {
			const cols = c.columns as string[];
			return cols?.length ? truncate(cols) : 'no column';
		}
	},
	timeseries: {
		label: 'Time Series',
		icon: Calendar,
		summary: (c) => {
			const col = c.column as string;
			const op = c.operation_type as string;
			const newCol = c.new_column as string;
			const component = c.component as string;
			const value = c.value as number;
			const unit = c.unit as string;
			if (!col || !op) return 'not configured';
			const detail =
				op === 'extract' && component
					? `.${component}`
					: value !== undefined && unit
						? `(${value} ${unit})`
						: unit
							? `(${unit})`
							: '';
			return `${col}.${op}${detail} → ${newCol}`;
		}
	},
	string_transform: {
		label: 'String Transform',
		icon: Type,
		summary: (c) => {
			const col = c.column as string;
			const method = c.method as string;
			const newCol = c.new_column as string;
			const pattern = c.pattern as string;
			const replacement = c.replacement as string;
			const delimiter = c.delimiter as string;
			if (!col || !method) return 'not configured';
			let args = '';
			if (pattern && replacement) args = `("${pattern}", "${replacement}")`;
			else if (pattern) args = `("${pattern}")`;
			else if (delimiter) args = `("${delimiter}")`;
			return `${col}.${method}${args} → ${newCol}`;
		}
	},
	sample: {
		label: 'Sample',
		icon: Dices,
		summary: (c) => {
			const frac = c.fraction as number | undefined;
			const seed = c.seed as number | null | undefined;
			if (frac === undefined) return 'not configured';
			const base = `${(frac * 100).toFixed(0)}%`;
			return seed === null || seed === undefined ? base : `${base} (seed: ${seed})`;
		}
	},
	limit: {
		label: 'Limit',
		icon: Scissors,
		summary: (c) => {
			const n = c.n as number;
			return n !== undefined ? `${n} rows` : 'not configured';
		}
	},
	topk: {
		label: 'Top K',
		icon: Trophy,
		summary: (c) => {
			const col = c.column as string;
			const k = c.k as number;
			const desc = c.descending as boolean;
			if (!col || k === undefined) return 'not configured';
			return `top ${k} by ${col} ${desc ? '▼' : '▲'}`;
		}
	},

	chart: {
		label: 'Chart',
		icon: ChartColumnIncreasing,
		summary: (c) => {
			const chartType = (c.chart_type as string) || 'chart';
			const x = c.x_column as string;
			const y = c.y_column as string;
			if (!x) return chartType;
			if (chartType === 'histogram') return `${chartType}: ${x}`;
			if (!y) return `${chartType}: ${x}`;
			if (chartType === 'line') return `${chartType}: ${y} over ${x}`;
			return `${chartType}: ${y} by ${x}`;
		}
	},
	notification: {
		label: 'Notify',
		icon: Bell,
		summary: (c) => {
			const method = (c.method as string) || 'email';
			return `via ${method}`;
		}
	},
	ai: {
		label: 'AI',
		icon: Sparkles,
		summary: (c) => {
			const cols = c.input_columns as string[] | undefined;
			const output = c.output_column as string;
			if (!cols?.length || !output) return 'not configured';
			return `${cols.join(', ')} → ${output}`;
		}
	},
	view: {
		label: 'View',
		icon: Eye,
		summary: (c) => `limit ${(c.rowLimit as number) ?? 100} rows`
	},
	union_by_name: {
		label: 'Union By Name',
		icon: LayoutGrid,
		summary: (c) => {
			const sources = c.sources as string[];
			const allowMissing = c.allow_missing as boolean;
			if (!sources?.length) return 'no sources';
			const base = `${sources.length} source${sources.length > 1 ? 's' : ''}`;
			return allowMissing ? `${base} (allow missing)` : base;
		}
	},
	export: {
		label: 'Export',
		icon: Upload,
		summary: (c) => {
			const filename = (c.filename as string) || 'export';
			const format = (c.format as string) || 'csv';
			const dest = (c.destination as string) || 'download';
			if (dest === 'datasource') {
				return 'datasource (iceberg)';
			}
			return `${filename}.${format}`;
		}
	},
	download: {
		label: 'Download',
		icon: Download,
		summary: (c) => {
			const filename = (c.filename as string) || 'download';
			const format = (c.format as string) || 'csv';
			return `${filename}.${format}`;
		}
	}
} satisfies Partial<Record<CanonicalStepType, StepTypeConfig>>;

function hasStepTypeConfig(type: string): type is keyof typeof stepTypes {
	return type in stepTypes;
}

const defaultStepType: StepTypeConfig = {
	label: 'Unknown',
	icon: Settings2,
	summary: () => 'click to configure'
};

function getStepTypeConfig(type: string): StepTypeConfig {
	if (isChartStepType(type)) return stepTypes.chart;
	if (hasStepTypeConfig(type)) {
		return stepTypes[type];
	}
	return defaultStepType;
}

function isChartStep(type: string): boolean {
	return isChartStepType(type);
}

function normalizeStepType(type: string): string {
	return normalizePipelineStepType(type);
}

export { type StepTypeConfig, stepTypes, getStepTypeConfig, isChartStep, normalizeStepType };
