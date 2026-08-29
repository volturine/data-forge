export type ChartRow = Record<string, unknown>;

export function numberValue(value: unknown): number {
	if (typeof value === 'number') return value;
	if (typeof value === 'string') return Number(value) || 0;
	return 0;
}

export function stringValue(value: unknown): string {
	return value == null ? '' : String(value);
}

export function groupOrder(
	rows: ChartRow[],
	groupKey: string,
	options: {
		mode: 'name' | 'value' | 'custom' | null;
		order: 'asc' | 'desc';
		customColumn: string;
	}
): string[] {
	const groups = [...new Set(rows.map((row) => stringValue(row[groupKey])))];
	if (!options.mode) return groups;
	if (options.mode === 'name') {
		return [...groups].sort((left, right) =>
			options.order === 'asc' ? left.localeCompare(right) : right.localeCompare(left)
		);
	}
	if (options.mode === 'value') {
		const totals = new Map<string, number>();
		for (const row of rows) {
			const key = stringValue(row[groupKey]);
			totals.set(key, (totals.get(key) ?? 0) + numberValue(row.y));
		}
		return [...groups].sort((left, right) => {
			const difference = (totals.get(left) ?? 0) - (totals.get(right) ?? 0);
			return options.order === 'asc' ? difference : -difference;
		});
	}
	if (!options.customColumn) return groups;
	const values = new Map<string, string>();
	for (const row of rows) {
		const key = stringValue(row[groupKey]);
		if (!values.has(key)) values.set(key, stringValue(row[options.customColumn]));
	}
	return [...groups].sort((left, right) => {
		const comparison = (values.get(left) ?? '').localeCompare(values.get(right) ?? '');
		return options.order === 'asc' ? comparison : -comparison;
	});
}
