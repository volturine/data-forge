// Polars data type constants and utilities

export const PolarsDType = {
	// Integer types
	Int8: 'Int8',
	Int16: 'Int16',
	Int32: 'Int32',
	Int64: 'Int64',
	UInt8: 'UInt8',
	UInt16: 'UInt16',
	UInt32: 'UInt32',
	UInt64: 'UInt64',

	// Float types
	Float32: 'Float32',
	Float64: 'Float64',

	// String types
	String: 'String',
	Utf8: 'Utf8',

	// Boolean type
	Boolean: 'Boolean',

	// Date/Time types
	Date: 'Date',
	Datetime: 'Datetime',
	Time: 'Time',
	Duration: 'Duration',

	// Other types
	Categorical: 'Categorical',
	List: 'List',
	Struct: 'Struct',
	Null: 'Null',
	Object: 'Object'
} as const;

export type PolarsDTypeValue = (typeof PolarsDType)[keyof typeof PolarsDType];

// Check if dtype is numeric
export function isNumericDType(dtype: string): boolean {
	const numericTypes: readonly string[] = [
		PolarsDType.Int8,
		PolarsDType.Int16,
		PolarsDType.Int32,
		PolarsDType.Int64,
		PolarsDType.UInt8,
		PolarsDType.UInt16,
		PolarsDType.UInt32,
		PolarsDType.UInt64,
		PolarsDType.Float32,
		PolarsDType.Float64
	];
	return numericTypes.includes(dtype);
}

// Check if dtype is integer
export function isIntegerDType(dtype: string): boolean {
	const integerTypes: readonly string[] = [
		PolarsDType.Int8,
		PolarsDType.Int16,
		PolarsDType.Int32,
		PolarsDType.Int64,
		PolarsDType.UInt8,
		PolarsDType.UInt16,
		PolarsDType.UInt32,
		PolarsDType.UInt64
	];
	return integerTypes.includes(dtype);
}

// Check if dtype is float
export function isFloatDType(dtype: string): boolean {
	const floatTypes: readonly string[] = [PolarsDType.Float32, PolarsDType.Float64];
	return floatTypes.includes(dtype);
}

// Check if dtype is temporal
export function isTemporalDType(dtype: string): boolean {
	const temporalTypes: readonly string[] = [
		PolarsDType.Date,
		PolarsDType.Datetime,
		PolarsDType.Time,
		PolarsDType.Duration
	];
	return temporalTypes.includes(dtype);
}

// Check if dtype is string-like
export function isStringDType(dtype: string): boolean {
	const stringTypes: readonly string[] = [
		PolarsDType.String,
		PolarsDType.Utf8,
		PolarsDType.Categorical
	];
	return stringTypes.includes(dtype);
}

// Aggregation result type mapping
export function getAggregationResultDType(aggFunc: string, inputDType: string): string {
	switch (aggFunc) {
		case 'count':
		case 'n_unique':
			return PolarsDType.UInt32;

		case 'sum':
			return isIntegerDType(inputDType) ? PolarsDType.Int64 : inputDType;

		case 'mean':
		case 'median':
		case 'std':
		case 'var':
			return PolarsDType.Float64;

		case 'min':
		case 'max':
		case 'first':
		case 'last':
			return inputDType;

		case 'list':
			return PolarsDType.List;

		default:
			return inputDType;
	}
}

// Expression result type mapping
export function getExpressionResultDType(
	expr: string,
	schema: { columns: { name: string; dtype: string }[] }
): string {
	// Simple heuristics for expression result types
	// In a real implementation, this would parse the expression properly

	// Arithmetic operations
	if (expr.includes('+') || expr.includes('-') || expr.includes('*') || expr.includes('/')) {
		return PolarsDType.Float64;
	}

	// String operations
	if (expr.includes('.str.') || expr.includes('concat')) {
		return PolarsDType.String;
	}

	// Comparison operations
	if (
		expr.includes('>') ||
		expr.includes('<') ||
		expr.includes('==') ||
		expr.includes('!=') ||
		expr.includes('>=') ||
		expr.includes('<=')
	) {
		return PolarsDType.Boolean;
	}

	// Date operations
	if (expr.includes('.dt.')) {
		if (expr.includes('.year') || expr.includes('.month') || expr.includes('.day')) {
			return PolarsDType.Int32;
		}
		return PolarsDType.Datetime;
	}

	// Try to find column reference and use its type
	const columnMatch = expr.match(/pl\.col\(['"](\w+)['"]\)/);
	if (columnMatch) {
		const column = schema.columns.find((c) => c.name === columnMatch[1]);
		if (column) return column.dtype;
	}

	// Default to string for unknown expressions
	return PolarsDType.String;
}
