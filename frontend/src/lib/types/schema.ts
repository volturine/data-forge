export interface Column {
	name: string;
	dtype: string;
	nullable: boolean;
}

// Alias for Column used in some places
export type ColumnInfo = Column;

export interface Schema {
	columns: Column[];
	row_count: number | null;
	sheet_names?: string[] | null;
}

export function emptySchema(): Schema {
	return { columns: [], row_count: null };
}

export function getColumn(schema: Schema | null, name: string): Column | null {
	if (!schema) return null;
	return schema.columns.find((c) => c.name === name) ?? null;
}

export function hasColumn(schema: Schema | null, name: string): boolean {
	if (!schema) return false;
	return schema.columns.some((c) => c.name === name);
}

export function columnNames(schema: Schema | null): string[] {
	if (!schema) return [];
	return schema.columns.map((c) => c.name);
}

export function unionByName(schemas: Schema[], _allowMissing: boolean = true): Schema {
	const columnMap = new Map<string, { dtype: string; nullable: boolean }>();

	for (const schema of schemas) {
		for (const col of schema.columns) {
			if (columnMap.has(col.name)) {
				const existing = columnMap.get(col.name)!;
				existing.nullable = existing.nullable || col.nullable;
				continue;
			}
			columnMap.set(col.name, {
				dtype: col.dtype,
				nullable: col.nullable
			});
		}
	}

	return {
		columns: Array.from(columnMap.entries()).map(([name, info]) => ({
			name,
			dtype: info.dtype,
			nullable: info.nullable
		})),
		row_count: null
	};
}

export function intersectSchemas(
	left: Schema,
	right: Schema | null,
	_suffix: string = '',
	rightColumns?: string[]
): Schema {
	const result: Column[] = [];

	for (const lcol of left.columns) {
		const rcol = right?.columns.find((c) => c.name === lcol.name);
		if (rcol) {
			result.push({
				name: lcol.name,
				dtype: lcol.dtype,
				nullable: lcol.nullable || rcol.nullable
			});
		}
	}

	// Add selected right columns that don't overlap with left
	if (right && rightColumns && rightColumns.length > 0) {
		for (const rcol of right.columns) {
			if (!hasColumn(left, rcol.name) && rightColumns.includes(rcol.name)) {
				result.push({
					name: rcol.name + _suffix,
					dtype: rcol.dtype,
					nullable: true
				});
			}
		}
	}

	return { columns: result, row_count: null };
}

export function leftJoinSchema(
	left: Schema,
	right: Schema | null,
	suffix: string = '_right',
	rightColumns?: string[]
): Schema {
	const result: Column[] = [];

	for (const lcol of left.columns) {
		result.push({ ...lcol });
	}

	if (right) {
		const rightFiltered =
			rightColumns && rightColumns.length > 0
				? right.columns.filter((c) => rightColumns.includes(c.name))
				: right.columns;

		for (const rcol of rightFiltered) {
			if (!hasColumn(left, rcol.name)) {
				result.push({
					name: rcol.name + suffix,
					dtype: rcol.dtype,
					nullable: true
				});
			}
		}
	}

	return { columns: result, row_count: null };
}

export function rightJoinSchema(
	left: Schema | null,
	right: Schema,
	suffix: string = '_left',
	rightColumns?: string[]
): Schema {
	const result: Column[] = [];

	if (left) {
		const leftFiltered =
			rightColumns && rightColumns.length > 0
				? left.columns.filter((c) => rightColumns.includes(c.name))
				: left.columns;

		for (const lcol of leftFiltered) {
			if (!hasColumn(right, lcol.name)) {
				result.push({
					name: lcol.name + suffix,
					dtype: lcol.dtype,
					nullable: true
				});
			}
		}
	}

	for (const rcol of right.columns) {
		result.push({ ...rcol });
	}

	return { columns: result, row_count: null };
}

export function outerJoinSchema(
	left: Schema,
	right: Schema | null,
	suffix: string = '_other',
	rightColumns?: string[]
): Schema {
	const result: Column[] = [];
	const rightSeen = new Set<string>();

	for (const lcol of left.columns) {
		const rcol = right?.columns.find((c) => c.name === lcol.name);
		if (rcol) {
			result.push({
				name: lcol.name,
				dtype: lcol.dtype,
				nullable: lcol.nullable || rcol.nullable
			});
			rightSeen.add(rcol.name);
			continue;
		}
		result.push({ ...lcol });
	}

	if (right) {
		const rightFiltered =
			rightColumns && rightColumns.length > 0
				? right.columns.filter((c) => rightColumns.includes(c.name))
				: right.columns;

		for (const rcol of rightFiltered) {
			if (!rightSeen.has(rcol.name)) {
				result.push({
					name: rcol.name + suffix,
					dtype: rcol.dtype,
					nullable: true
				});
			}
		}
	}

	return { columns: result, row_count: null };
}

export function crossJoinSchema(left: Schema, right: Schema): Schema {
	const result: Column[] = [];

	for (const lcol of left.columns) {
		result.push({ ...lcol });
	}

	for (const rcol of right.columns) {
		result.push({ ...rcol });
	}

	return { columns: result, row_count: null };
}
