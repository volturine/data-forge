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
 * console.log(config.label); // "Int64"
 * console.log(config.category); // "integer"
 *
 * // Normalize Polars type strings from backend
 * const normalized = normalizeColumnType("Datetime(time_unit='us', time_zone=None)");
 * console.log(normalized); // "Datetime"
 *
 * // Handle aliases
 * const stringType = normalizeColumnType('Utf8'); // Returns 'String'
 * ```
 */

import type { ComponentType } from 'svelte';
import { Type, Hash, Binary, Calendar, ToggleLeft, Layers, HelpCircle, File } from 'lucide-svelte';

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
	| 'Unknown';

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

/**
 * Mapping of backend values to canonical display names
 */
const CANONICAL_NAMES: Record<string, string> = {
	Utf8: 'String',
	str: 'String',
	int: 'Int64',
	float: 'Float64',
	bool: 'Boolean',
	Timestamp: 'Datetime'
};

/**
 * Category configurations with default colors and icons
 */
export const CATEGORY_REGISTRY: Record<ColumnTypeCategory, CategoryConfig> = {
	string: {
		category: 'string',
		label: 'String',
		colors: {
			color: '#16a34a',
			borderColor: 'rgba(22, 163, 74, 0.45)',
			backgroundColor: 'rgba(22, 163, 74, 0.12)'
		},
		icon: Type
	},
	integer: {
		category: 'integer',
		label: 'Integer',
		colors: {
			color: '#2563eb',
			borderColor: 'rgba(37, 99, 235, 0.45)',
			backgroundColor: 'rgba(37, 99, 235, 0.12)'
		},
		icon: Hash
	},
	float: {
		category: 'float',
		label: 'Float',
		colors: {
			color: '#6366f1',
			borderColor: 'rgba(99, 102, 241, 0.45)',
			backgroundColor: 'rgba(99, 102, 241, 0.12)'
		},
		icon: Binary
	},
	temporal: {
		category: 'temporal',
		label: 'Temporal',
		colors: {
			color: '#ea580c',
			borderColor: 'rgba(234, 88, 12, 0.45)',
			backgroundColor: 'rgba(234, 88, 12, 0.12)'
		},
		icon: Calendar
	},
	boolean: {
		category: 'boolean',
		label: 'Boolean',
		colors: {
			color: '#f59e0b',
			borderColor: 'rgba(245, 158, 11, 0.45)',
			backgroundColor: 'rgba(245, 158, 11, 0.12)'
		},
		icon: ToggleLeft
	},
	complex: {
		category: 'complex',
		label: 'Complex',
		colors: {
			color: '#9333ea',
			borderColor: 'rgba(147, 51, 234, 0.45)',
			backgroundColor: 'rgba(147, 51, 234, 0.12)'
		},
		icon: Layers
	},
	other: {
		category: 'other',
		label: 'Other',
		colors: {
			color: '#64748b',
			borderColor: 'rgba(100, 116, 139, 0.45)',
			backgroundColor: 'rgba(100, 116, 139, 0.12)'
		},
		icon: HelpCircle
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
		icon: HelpCircle,
		description: 'Binary data',
		aliases: []
	},
	Object: {
		type: 'Object',
		label: 'Object',
		canonicalName: 'Object',
		category: 'other',
		colors: CATEGORY_REGISTRY.other.colors,
		icon: HelpCircle,
		description: 'Python object (mixed type)',
		aliases: []
	},
	Null: {
		type: 'Null',
		label: 'Null',
		canonicalName: 'Null',
		category: 'other',
		colors: CATEGORY_REGISTRY.other.colors,
		icon: HelpCircle,
		description: 'Null type',
		aliases: []
	},
	Unknown: {
		type: 'Unknown',
		label: 'Unknown',
		canonicalName: 'Unknown',
		category: 'other',
		colors: CATEGORY_REGISTRY.other.colors,
		icon: File,
		description: 'Unknown type',
		aliases: []
	}
};

/**
 * Detects if a type string represents a complex/nested type
 * Examples: "List<Int64>", "Array<String>", "Struct{name: String, age: Int64}"
 */
export function detectComplexType(type: string): boolean {
	const lowercased = type.toLowerCase();
	return (
		lowercased.includes('list') ||
		lowercased.includes('array') ||
		lowercased.includes('struct') ||
		lowercased.includes('<') ||
		lowercased.includes('{')
	);
}

/**
 * Normalizes column type names to their canonical form
 * Examples: 'Utf8' -> 'String', 'int' -> 'Int64', 'bool' -> 'Boolean'
 *
 * Handles Polars' parameterized type formats:
 * - "Datetime(time_unit='us', time_zone=None)" -> "Datetime"
 * - "Duration(time_unit='us')" -> "Duration"
 * - "List(Int64)" -> "List"
 * - "Struct({'a': Int64})" -> "Struct"
 */
export function normalizeColumnType(type: string): string {
	// Handle parameterized types - extract base type name before parenthesis
	// Examples: "Datetime(time_unit='us')" -> "Datetime", "List(Int64)" -> "List"
	const paramMatch = type.match(/^([A-Za-z0-9]+)\(/);
	if (paramMatch) {
		const baseType = paramMatch[1];

		// Map common base types to canonical names
		const baseTypeMap: Record<string, string> = {
			Datetime: 'Datetime',
			Duration: 'Duration',
			List: 'List',
			Array: 'List', // Normalize Array to List
			Struct: 'Struct',
			Timestamp: 'Datetime' // Timestamp is just Datetime
		};

		if (baseType in baseTypeMap) {
			return baseTypeMap[baseType];
		}

		// If it's a known type, use it
		if (baseType in COLUMN_TYPE_REGISTRY) {
			return COLUMN_TYPE_REGISTRY[baseType as ColumnType].canonicalName;
		}

		return baseType;
	}

	// Check if it's a known alias
	if (type in CANONICAL_NAMES) {
		return CANONICAL_NAMES[type];
	}

	// Check if it's already in the registry
	if (type in COLUMN_TYPE_REGISTRY) {
		return COLUMN_TYPE_REGISTRY[type as ColumnType].canonicalName;
	}

	// Check if it's a complex type (legacy format with < or {)
	if (detectComplexType(type)) {
		// Try to extract base type (e.g., "List<Int64>" -> "List")
		const match = type.match(/^(List|Array|Struct)/i);
		if (match) {
			const baseType = match[1];
			// Normalize to List for Array
			return baseType.toLowerCase() === 'array' ? 'List' : baseType;
		}
		return 'List'; // Default to List for complex types
	}

	// Return as-is if we can't normalize
	return type;
}

/**
 * Gets the full configuration for a column type
 * Handles aliases and complex types automatically
 */
export function getColumnTypeConfig(type: string): ColumnTypeConfig {
	// Normalize the type first
	const normalized = normalizeColumnType(type);

	// Check if it exists in registry
	if (normalized in COLUMN_TYPE_REGISTRY) {
		return COLUMN_TYPE_REGISTRY[normalized as ColumnType];
	}

	// Check for complex types
	if (detectComplexType(type)) {
		return COLUMN_TYPE_REGISTRY.List;
	}

	// Fallback to Unknown
	return COLUMN_TYPE_REGISTRY.Unknown;
}

/**
 * Gets just the colors for a column type
 */
export function getColumnTypeColors(type: string): ColumnTypeColors {
	return getColumnTypeConfig(type).colors;
}

/**
 * Gets just the icon component for a column type
 */
export function getColumnTypeIcon(type: string): ComponentType {
	return getColumnTypeConfig(type).icon;
}

/**
 * Gets just the category for a column type
 */
export function getColumnTypeCategory(type: string): ColumnTypeCategory {
	return getColumnTypeConfig(type).category;
}

/**
 * Gets the display label for a column type (normalized)
 */
export function getColumnTypeLabel(type: string): string {
	return getColumnTypeConfig(type).label;
}

/**
 * Groups column types by category for use in optgroups
 * Returns a map of category -> array of type configs
 */
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

	// Get unique types only (skip aliases like Utf8)
	const uniqueTypes = new Set<string>();
	Object.values(COLUMN_TYPE_REGISTRY).forEach((config) => {
		if (!uniqueTypes.has(config.canonicalName)) {
			uniqueTypes.add(config.canonicalName);
			grouped[config.category].push(config);
		}
	});

	return grouped;
}

/**
 * Gets all column types as a flat array (for simple dropdowns)
 * Only includes canonical types (no aliases)
 */
export function getAllColumnTypes(): ColumnTypeConfig[] {
	const unique = new Set<string>();
	const types: ColumnTypeConfig[] = [];

	Object.values(COLUMN_TYPE_REGISTRY).forEach((config) => {
		if (!unique.has(config.canonicalName)) {
			unique.add(config.canonicalName);
			types.push(config);
		}
	});

	return types;
}

/**
 * Checks if a type string is a valid column type
 */
export function isValidColumnType(type: string): boolean {
	const normalized = normalizeColumnType(type);
	return normalized in COLUMN_TYPE_REGISTRY || detectComplexType(type);
}
