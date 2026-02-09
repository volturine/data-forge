import {
	ArrowUpDown,
	BarChart3,
	Bomb,
	Brush,
	Calculator,
	Calendar,
	CircleHelp,
	Dices,
	Eye,
	Filter,
	LayoutGrid,
	Link,
	Pencil,
	Repeat,
	Repeat2,
	Scissors,
	Settings2,
	Trophy,
	Type,
	Upload,
	Wrench,
	ListChecks,
	Trash2
} from 'lucide-svelte';

function truncate(items: string[], max = 3, len = 20): string {
	if (!items?.length) return '';
	const shown = items
		.slice(0, max)
		.map((item) => (item.length > len ? item.slice(0, len - 1) + '…' : item));
	return items.length > max ? `${shown.join(', ')} +${items.length - max}` : shown.join(', ');
}

type StepTypeConfig = {
	label: string;
	icon: typeof Filter;
	typeLabel: string;
	summary: (c: Record<string, unknown>) => string;
};

const stepTypes: Record<string, StepTypeConfig> = {
	filter: {
		label: 'Filter',
		icon: Filter,
		typeLabel: 'filter',
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
		typeLabel: 'select',
		summary: (c) => {
			const cols = c.columns as string[];
			return cols?.length ? truncate(cols) : 'no columns';
		}
	},
	groupby: {
		label: 'Group By',
		icon: BarChart3,
		typeLabel: 'group_by',
		summary: (c) => {
			const keys = c.groupBy as string[];
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
		typeLabel: 'sort',
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
		typeLabel: 'rename',
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
		typeLabel: 'drop',
		summary: (c) => {
			const cols = c.columns as string[];
			return cols?.length ? truncate(cols) : 'no columns';
		}
	},
	join: {
		label: 'Join',
		icon: Link,
		typeLabel: 'join',
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
		typeLabel: 'expression',
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
		typeLabel: 'with_columns',
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
		typeLabel: 'pivot',
		summary: (c) => {
			const col = c.columns as string;
			const vals = c.values as string;
			const agg = c.aggregate_function as string;
			const idx = c.index as string[];
			if (!col || !vals) return 'not configured';
			const base = `${col} → ${agg}(${vals})`;
			return idx?.length ? `${base}, index: ${truncate(idx, 2, 15)}` : base;
		}
	},
	unpivot: {
		label: 'Unpivot',
		icon: Repeat2,
		typeLabel: 'unpivot',
		summary: (c) => {
			const on = c.on as string[];
			const varName = (c.variable_name as string) || 'variable';
			const valName = (c.value_name as string) || 'value';
			if (!on?.length) return 'not configured';
			return `${truncate(on, 2)} → (${varName}, ${valName})`;
		}
	},
	fill_null: {
		label: 'Fill Null',
		icon: Wrench,
		typeLabel: 'fill_null',
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
		typeLabel: 'deduplicate',
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
		typeLabel: 'explode',
		summary: (c) => {
			const cols = c.columns as string[];
			return cols?.length ? truncate(cols) : 'no column';
		}
	},
	timeseries: {
		label: 'Time Series',
		icon: Calendar,
		typeLabel: 'timeseries',
		summary: (c) => {
			const col = c.column as string;
			const op = c.operation_type as string;
			const newCol = c.new_column as string;
			const component = c.component as string;
			const value = c.value as number;
			const unit = c.unit as string;
			if (!col || !op) return 'not configured';
			const detail = component ? `.${component}` : value && unit ? `(${value} ${unit})` : '';
			return `${col}.${op}${detail} → ${newCol}`;
		}
	},
	string_transform: {
		label: 'String Transform',
		icon: Type,
		typeLabel: 'string',
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
		typeLabel: 'sample',
		summary: (c) => {
			const frac = c.fraction as number | undefined;
			const seed = c.seed as number | undefined;
			if (frac === undefined) return 'not configured';
			const base = `${(frac * 100).toFixed(0)}%`;
			const extras = seed !== undefined ? `seed: ${seed}` : '';
			return extras ? `${base} (${extras})` : base;
		}
	},
	limit: {
		label: 'Limit',
		icon: Scissors,
		typeLabel: 'limit',
		summary: (c) => {
			const n = c.n as number;
			return n !== undefined ? `${n} rows` : 'not configured';
		}
	},
	topk: {
		label: 'Top K',
		icon: Trophy,
		typeLabel: 'topk',
		summary: (c) => {
			const col = c.column as string;
			const k = c.k as number;
			const desc = c.descending as boolean;
			if (!col || k === undefined) return 'not configured';
			return `top ${k} by ${col} ${desc ? '▼' : '▲'}`;
		}
	},
	null_count: {
		label: 'Null Count',
		icon: CircleHelp,
		typeLabel: 'null_count',
		summary: () => 'count nulls per column'
	},
	value_counts: {
		label: 'Value Counts',
		icon: BarChart3,
		typeLabel: 'value_counts',
		summary: (c) => {
			const col = c.column as string;
			const norm = c.normalize as boolean;
			const sort = c.sort as boolean;
			if (!col) return 'not configured';
			const extras = [];
			if (norm) extras.push('%');
			if (sort) extras.push('sorted');
			return extras.length ? `${col} (${extras.join(', ')})` : col;
		}
	},
	view: {
		label: 'View',
		icon: Eye,
		typeLabel: 'view',
		summary: (c) => `limit ${(c.rowLimit as number) ?? 100} rows`
	},
	union_by_name: {
		label: 'Union By Name',
		icon: LayoutGrid,
		typeLabel: 'union_by_name',
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
		typeLabel: 'export',
		summary: (c) => {
			const filename = (c.filename as string) || 'export';
			const format = (c.format as string) || 'csv';
			const dest = (c.destination as string) || 'download';
			return dest === 'filesystem'
				? `${filename}.${format} (save to disk)`
				: `${filename}.${format}`;
		}
	}
};

const defaultStepType: StepTypeConfig = {
	label: 'Unknown',
	icon: Settings2,
	typeLabel: 'unknown',
	summary: () => 'click to configure'
};

function getStepTypeConfig(type: string): StepTypeConfig {
	return stepTypes[type] ?? defaultStepType;
}

export { type StepTypeConfig, defaultStepType, stepTypes, getStepTypeConfig };
