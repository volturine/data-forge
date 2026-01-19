export interface Column {
	name: string;
	dtype: string;
	nullable: boolean;
}

export interface Schema {
	columns: Column[];
	row_count: number | null;
}

export function emptySchema(): Schema {
	return { columns: [], row_count: null };
}

export function getColumn(schema: Schema | null, name: string): Column | null {
	if (!schema) return null;
	return schema.columns.find(c => c.name === name) ?? null;
}

export function hasColumn(schema: Schema | null, name: string): boolean {
	if (!schema) return false;
	return schema.columns.some(c => c.name === name);
}

export function columnNames(schema: Schema | null): string[] {
	if (!schema) return [];
	return schema.columns.map(c => c.name);
}

export function unionByName(schemas: Schema[], allowMissing: boolean = true): Schema {
	const columnMap = new Map<string, { dtype: string; nullable: boolean }>();

	for (const schema of schemas) {
		for (const col of schema.columns) {
			if (columnMap.has(col.name)) {
				const existing = columnMap.get(col.name)!;
				existing.nullable = existing.nullable || col.nullable;
			} else {
				columnMap.set(col.name, {
					dtype: col.dtype,
					nullable: col.nullable
				});
			}
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

export function intersectSchemas(left: Schema, right: Schema, suffix: string = ''): Schema {
	const result: Column[] = [];

	for (const lcol of left.columns) {
		const rcol = right.columns.find(c => c.name === lcol.name);
		if (rcol) {
			result.push({
				name: lcol.name,
				dtype: lcol.dtype,
				nullable: lcol.nullable || rcol.nullable
			});
		}
	}

	return { columns: result, row_count: null };
}

export function leftJoinSchema(left: Schema, right: Schema, suffix: string = '_right'): Schema {
	const result: Column[] = [];

	for (const lcol of left.columns) {
		result.push({ ...lcol });
	}

	const rightColumns = right.columns.filter(c => !hasColumn(left, c.name));
	for (const rcol of rightColumns) {
		result.push({
			name: rcol.name + suffix,
			dtype: rcol.dtype,
			nullable: true
		});
	}

	return { columns: result, row_count: null };
}

export function rightJoinSchema(left: Schema, right: Schema, suffix: string = '_left'): Schema {
	const result: Column[] = [];

	const leftColumns = left.columns.filter(c => !hasColumn(right, c.name));
	for (const lcol of leftColumns) {
		result.push({
			name: lcol.name + suffix,
			dtype: lcol.dtype,
			nullable: true
		});
	}

	for (const rcol of right.columns) {
		result.push({ ...rcol });
	}

	return { columns: result, row_count: null };
}

export function outerJoinSchema(left: Schema, right: Schema, suffix: string = '_other'): Schema {
	const result: Column[] = [];
	const rightSeen = new Set<string>();

	for (const lcol of left.columns) {
		const rcol = right.columns.find(c => c.name === lcol.name);
		if (rcol) {
			result.push({
				name: lcol.name,
				dtype: lcol.dtype,
				nullable: lcol.nullable || rcol.nullable
			});
			rightSeen.add(rcol.name);
		} else {
			result.push({ ...lcol });
		}
	}

	for (const rcol of right.columns) {
		if (!rightSeen.has(rcol.name)) {
			result.push({
				name: rcol.name + suffix,
				dtype: rcol.dtype,
				nullable: true
			});
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

