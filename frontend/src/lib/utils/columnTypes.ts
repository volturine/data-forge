/**
 * Unified Column Type System
 *
 * This module provides a centralized source of truth for all column type representations
 * across the application, including colors, icons, labels, and type detection.
 *
 * Handles Polars' parameterized type formats from the backend:
 * - Temporal types: "Datetime(time_unit='us', time_zone=None)" -> "Datetime"
 * - Duration types: "Duration(time_unit='us')" -> "Duration"
 * - Complex types: "List(Int64)", "Struct({'a': Int64, 'b': String})" -> "List", "Struct"
 * - Simple types: "String", "Int64", "Float64", etc. (passed through as-is)
 *
 * Usage:
 * ```typescript
 * import { getColumnTypeConfig, normalizeColumnType } from '$lib/utils/columnTypes';
 *
 * // Get full configuration for a type
 * const config = getColumnTypeConfig('Int64');
 * Example: config.label === "Int64"
 * Example: config.category === "integer"
 *
 * // Normalize Polars type strings from backend
 * const normalized = normalizeColumnType("Datetime(time_unit='us', time_zone=None)");
 * Example: normalized === "Datetime"
 *
 * // Handle aliases
 * const stringType = normalizeColumnType('Utf8'); // Returns 'String'
 * ```
 */

import type { ComponentType } from 'svelte';
import {
	Type,
	Hash,
	Binary,
	Calendar,
	ToggleLeft,
	Layers,
	CircleQuestionMark,
	File
} from 'lucide-svelte';

/**
 * Supported column types (Polars data types)
 */
export type ColumnType =
	// String types
	| 'String'
	| 'Utf8'
	| 'Categorical'
	// Integer types
	| 'Int8'
	| 'Int16'
	| 'Int32'
	| 'Int64'
	| 'UInt8'
	| 'UInt16'
	| 'UInt32'
	| 'UInt64'
	// Float types
	| 'Float32'
	| 'Float64'
	// Temporal types
	| 'Date'
	| 'Datetime'
	| 'Timestamp'
	| 'Time'
	| 'Duration'
	// Boolean
	| 'Boolean'
	// Complex types
	| 'List'
	| 'Array'
	| 'Struct'
	// Other
	| 'Binary'
	| 'Object'
	| 'Null'
	| 'Any';

/**
 * Column type categories for grouping and color-coding
 */
export type ColumnTypeCategory =
	| 'string'
	| 'integer'
	| 'float'
	| 'temporal'
	| 'boolean'
	| 'complex'
	| 'other';

/**
 * Color scheme for a column type (CSS-in-JS format)
 */
export interface ColumnTypeColors {
	/** Main foreground color */
	color: string;
	/** Border color with transparency */
	borderColor: string;
	/** Background color with transparency */
	backgroundColor: string;
}

/**
 * Complete configuration for a column type
 */
export interface ColumnTypeConfig {
	/** Column type identifier */
	type: ColumnType;
	/** Display label */
	label: string;
	/** Canonical name (for alias normalization) */
	canonicalName: string;
	/** Type category */
	category: ColumnTypeCategory;
	/** Color scheme */
	colors: ColumnTypeColors;
	/** Lucide icon component */
	icon: ComponentType;
	/** Human-readable description */
	description: string;
	/** Alternative names/aliases */
	aliases: string[];
}

/**
 * Configuration for a type category
 */
export interface CategoryConfig {
	category: ColumnTypeCategory;
	label: string;
	colors: ColumnTypeColors;
	icon: ComponentType;
}

// Aliases for Python/Polars shorthand names not present in COLUMN_TYPE_REGISTRY
const _ALIASES: Record<string, string> = {
	str: 'String',
	int: 'Int64',
	float: 'Float64',
	bool: 'Boolean',
	Unknown: 'Any',
	unknown: 'Any'
};

/**
 * Category configurations with default colors and icons
 */
export const CATEGORY_REGISTRY: Record<ColumnTypeCategory, CategoryConfig> = {
	string: {
		category: 'string',
		label: 'String',
		colors: {
			color: 'var(--type-string-fg)',
			borderColor: 'var(--type-string-border)',
			backgroundColor: 'var(--type-string-bg)'
		},
		icon: Type
	},
	integer: {
		category: 'integer',
		label: 'Integer',
		colors: {
			color: 'var(--type-integer-fg)',
			borderColor: 'var(--type-integer-border)',
			backgroundColor: 'var(--type-integer-bg)'
		},
		icon: Hash
	},
	float: {
		category: 'float',
		label: 'Float',
		colors: {
			color: 'var(--type-float-fg)',
			borderColor: 'var(--type-float-border)',
			backgroundColor: 'var(--type-float-bg)'
		},
		icon: Binary
	},
	temporal: {
		category: 'temporal',
		label: 'Temporal',
		colors: {
			color: 'var(--type-temporal-fg)',
			borderColor: 'var(--type-temporal-border)',
			backgroundColor: 'var(--type-temporal-bg)'
		},
		icon: Calendar
	},
	boolean: {
		category: 'boolean',
		label: 'Boolean',
		colors: {
			color: 'var(--type-boolean-fg)',
			borderColor: 'var(--type-boolean-border)',
			backgroundColor: 'var(--type-boolean-bg)'
		},
		icon: ToggleLeft
	},
	complex: {
		category: 'complex',
		label: 'Complex',
		colors: {
			color: 'var(--type-complex-fg)',
			borderColor: 'var(--type-complex-border)',
			backgroundColor: 'var(--type-complex-bg)'
		},
		icon: Layers
	},
	other: {
		category: 'other',
		label: 'Other',
		colors: {
			color: 'var(--type-other-fg)',
			borderColor: 'var(--type-other-border)',
			backgroundColor: 'var(--type-other-bg)'
		},
		icon: CircleQuestionMark
	}
};

/**
 * Central registry of all column type configurations
 * This is the single source of truth for column type representations
 */
export const COLUMN_TYPE_REGISTRY: Record<ColumnType, ColumnTypeConfig> = {
	// String types
	String: {
		type: 'String',
		label: 'String',
		canonicalName: 'String',
		category: 'string',
		colors: CATEGORY_REGISTRY.string.colors,
		icon: Type,
		description: 'Text data (UTF-8)',
		aliases: ['Utf8', 'str']
	},
	Utf8: {
		type: 'Utf8',
		label: 'String',
		canonicalName: 'String',
		category: 'string',
		colors: CATEGORY_REGISTRY.string.colors,
		icon: Type,
		description: 'Text data (UTF-8)',
		aliases: ['String', 'str']
	},
	Categorical: {
		type: 'Categorical',
		label: 'Categorical',
		canonicalName: 'Categorical',
		category: 'string',
		colors: CATEGORY_REGISTRY.string.colors,
		icon: Type,
		description: 'Categorical data (enum-like)',
		aliases: []
	},

	// Integer types
	Int8: {
		type: 'Int8',
		label: 'Int8',
		canonicalName: 'Int8',
		category: 'integer',
		colors: CATEGORY_REGISTRY.integer.colors,
		icon: Hash,
		description: '8-bit signed integer',
		aliases: []
	},
	Int16: {
		type: 'Int16',
		label: 'Int16',
		canonicalName: 'Int16',
		category: 'integer',
		colors: CATEGORY_REGISTRY.integer.colors,
		icon: Hash,
		description: '16-bit signed integer',
		aliases: []
	},
	Int32: {
		type: 'Int32',
		label: 'Int32',
		canonicalName: 'Int32',
		category: 'integer',
		colors: CATEGORY_REGISTRY.integer.colors,
		icon: Hash,
		description: '32-bit signed integer',
		aliases: []
	},
	Int64: {
		type: 'Int64',
		label: 'Int64',
		canonicalName: 'Int64',
		category: 'integer',
		colors: CATEGORY_REGISTRY.integer.colors,
		icon: Hash,
		description: '64-bit signed integer',
		aliases: ['int']
	},
	UInt8: {
		type: 'UInt8',
		label: 'UInt8',
		canonicalName: 'UInt8',
		category: 'integer',
		colors: CATEGORY_REGISTRY.integer.colors,
		icon: Hash,
		description: '8-bit unsigned integer',
		aliases: []
	},
	UInt16: {
		type: 'UInt16',
		label: 'UInt16',
		canonicalName: 'UInt16',
		category: 'integer',
		colors: CATEGORY_REGISTRY.integer.colors,
		icon: Hash,
		description: '16-bit unsigned integer',
		aliases: []
	},
	UInt32: {
		type: 'UInt32',
		label: 'UInt32',
		canonicalName: 'UInt32',
		category: 'integer',
		colors: CATEGORY_REGISTRY.integer.colors,
		icon: Hash,
		description: '32-bit unsigned integer',
		aliases: []
	},
	UInt64: {
		type: 'UInt64',
		label: 'UInt64',
		canonicalName: 'UInt64',
		category: 'integer',
		colors: CATEGORY_REGISTRY.integer.colors,
		icon: Hash,
		description: '64-bit unsigned integer',
		aliases: []
	},

	// Float types
	Float32: {
		type: 'Float32',
		label: 'Float32',
		canonicalName: 'Float32',
		category: 'float',
		colors: CATEGORY_REGISTRY.float.colors,
		icon: Binary,
		description: '32-bit floating point',
		aliases: []
	},
	Float64: {
		type: 'Float64',
		label: 'Float64',
		canonicalName: 'Float64',
		category: 'float',
		colors: CATEGORY_REGISTRY.float.colors,
		icon: Binary,
		description: '64-bit floating point',
		aliases: ['float']
	},

	// Temporal types
	Date: {
		type: 'Date',
		label: 'Date',
		canonicalName: 'Date',
		category: 'temporal',
		colors: CATEGORY_REGISTRY.temporal.colors,
		icon: Calendar,
		description: 'Calendar date',
		aliases: []
	},
	Datetime: {
		type: 'Datetime',
		label: 'Datetime',
		canonicalName: 'Datetime',
		category: 'temporal',
		colors: CATEGORY_REGISTRY.temporal.colors,
		icon: Calendar,
		description: 'Date and time',
		aliases: ['Timestamp']
	},
	Timestamp: {
		type: 'Timestamp',
		label: 'Timestamp',
		canonicalName: 'Datetime',
		category: 'temporal',
		colors: CATEGORY_REGISTRY.temporal.colors,
		icon: Calendar,
		description: 'Timestamp (alias for Datetime)',
		aliases: ['Datetime']
	},
	Time: {
		type: 'Time',
		label: 'Time',
		canonicalName: 'Time',
		category: 'temporal',
		colors: CATEGORY_REGISTRY.temporal.colors,
		icon: Calendar,
		description: 'Time of day',
		aliases: []
	},
	Duration: {
		type: 'Duration',
		label: 'Duration',
		canonicalName: 'Duration',
		category: 'temporal',
		colors: CATEGORY_REGISTRY.temporal.colors,
		icon: Calendar,
		description: 'Time duration',
		aliases: []
	},

	// Boolean
	Boolean: {
		type: 'Boolean',
		label: 'Boolean',
		canonicalName: 'Boolean',
		category: 'boolean',
		colors: CATEGORY_REGISTRY.boolean.colors,
		icon: ToggleLeft,
		description: 'True or false',
		aliases: ['bool']
	},

	// Complex types
	List: {
		type: 'List',
		label: 'List',
		canonicalName: 'List',
		category: 'complex',
		colors: CATEGORY_REGISTRY.complex.colors,
		icon: Layers,
		description: 'List of values',
		aliases: ['Array']
	},
	Array: {
		type: 'Array',
		label: 'Array',
		canonicalName: 'List',
		category: 'complex',
		colors: CATEGORY_REGISTRY.complex.colors,
		icon: Layers,
		description: 'Array of values',
		aliases: ['List']
	},
	Struct: {
		type: 'Struct',
		label: 'Struct',
		canonicalName: 'Struct',
		category: 'complex',
		colors: CATEGORY_REGISTRY.complex.colors,
		icon: Layers,
		description: 'Structured data',
		aliases: []
	},

	// Other
	Binary: {
		type: 'Binary',
		label: 'Binary',
		canonicalName: 'Binary',
		category: 'other',
		colors: CATEGORY_REGISTRY.other.colors,
		icon: CircleQuestionMark,
		description: 'Binary data',
		aliases: []
	},
	Object: {
		type: 'Object',
		label: 'Object',
		canonicalName: 'Object',
		category: 'other',
		colors: CATEGORY_REGISTRY.other.colors,
		icon: CircleQuestionMark,
		description: 'Python object (mixed type)',
		aliases: []
	},
	Null: {
		type: 'Null',
		label: 'Null',
		canonicalName: 'Null',
		category: 'other',
		colors: CATEGORY_REGISTRY.other.colors,
		icon: CircleQuestionMark,
		description: 'Null type',
		aliases: []
	},
	Any: {
		type: 'Any',
		label: 'Any',
		canonicalName: 'Any',
		category: 'other',
		colors: CATEGORY_REGISTRY.other.colors,
		icon: File,
		description: 'Any type',
		aliases: ['Unknown', 'unknown']
	}
};

export function normalizeColumnType(type: string): string {
	const base = type.match(/^([A-Za-z0-9]+)[(<{]/)?.[1] ?? type;
	return COLUMN_TYPE_REGISTRY[base as ColumnType]?.canonicalName ?? _ALIASES[base] ?? base;
}

export function getColumnTypeConfig(type: string): ColumnTypeConfig {
	const normalized = normalizeColumnType(type);
	return COLUMN_TYPE_REGISTRY[normalized as ColumnType] ?? COLUMN_TYPE_REGISTRY.Any;
}

/**
 * Resolves a column type string to a canonical type with safe fallback.
 */
export function resolveColumnType(type?: string | null): string {
	if (!type) return COLUMN_TYPE_REGISTRY.Any.canonicalName;
	return getColumnTypeConfig(type).canonicalName;
}

function canonicalTypes(): ColumnTypeConfig[] {
	const seen = new Set<string>();
	return Object.values(COLUMN_TYPE_REGISTRY).filter((c) => {
		if (seen.has(c.canonicalName)) return false;
		seen.add(c.canonicalName);
		return true;
	});
}

export function getColumnTypesByCategory(): Record<ColumnTypeCategory, ColumnTypeConfig[]> {
	const grouped: Record<ColumnTypeCategory, ColumnTypeConfig[]> = {
		string: [],
		integer: [],
		float: [],
		temporal: [],
		boolean: [],
		complex: [],
		other: []
	};
	for (const config of canonicalTypes()) grouped[config.category].push(config);
	return grouped;
}

export function getAllColumnTypes(): ColumnTypeConfig[] {
	return canonicalTypes();
}

export function isValidColumnType(type: string): boolean {
	return normalizeColumnType(type) in COLUMN_TYPE_REGISTRY;
}
