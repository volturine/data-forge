/**
 * Unified File Type System
 *
 * This module provides a centralized source of truth for all file type representations
 * across the application, including colors, icons, labels, and type detection.
 *
 * Usage:
 * ```typescript
 * import { detectFileType, getFileTypeConfig } from '$lib/utils/fileTypes';
 *
 * const fileType = detectFileType('data.parquet');
 * const config = getFileTypeConfig(fileType);
 * ```
 */

import type { ComponentType } from 'svelte';
import {
	FileSpreadsheet,
	FileType as FileTypeIcon,
	FileBracesCorner,
	Database,
	FileCode,
	Layers,
	Snowflake,
	Folder as FolderIcon,
	File
} from 'lucide-svelte';

/**
 * Supported file types
 */
export type FileType =
	| 'csv'
	| 'parquet'
	| 'json'
	| 'ndjson'
	| 'excel'
	| 'arrow'
	| 'avro'
	| 'delta'
	| 'iceberg'
	| 'folder'
	| 'unknown';

/**
 * Supported datasource types (non-file sources)
 */
export type SourceType = 'database' | 'iceberg' | 'file' | 'analysis' | 'duckdb';

export type SourceCategory = 'file' | 'database' | 'analysis' | 'duckdb';

export const SOURCE_TYPE_CATEGORY: Record<SourceType, SourceCategory> = {
	file: 'file',
	iceberg: 'file',
	database: 'database',
	analysis: 'analysis',
	duckdb: 'duckdb'
};

/**
 * Color scheme for a file type (CSS-in-JS format)
 */
export interface FileTypeColors {
	/** Main foreground color */
	color: string;
	/** Border color with transparency */
	borderColor: string;
	/** Background color with transparency */
	backgroundColor: string;
}

/**
 * Complete configuration for a file type
 */
export interface FileTypeConfig {
	/** File type identifier */
	type: FileType;
	/** Display label */
	label: string;
	/** File extensions (including the dot) */
	extensions: string[];
	/** Color scheme */
	colors: FileTypeColors;
	/** Lucide icon component */
	icon: ComponentType;
	/** Human-readable description */
	description: string;
}

/**
 * Central registry of all file type configurations
 * This is the single source of truth for file type representations
 */
export const FILE_TYPE_REGISTRY: Record<FileType, FileTypeConfig> = {
	csv: {
		type: 'csv',
		label: 'CSV',
		extensions: ['.csv', '.tsv'],
		colors: {
			color: 'var(--file-csv-fg)',
			borderColor: 'var(--file-csv-border)',
			backgroundColor: 'var(--file-csv-bg)'
		},
		icon: FileSpreadsheet,
		description: 'Comma-separated or Tab-separated values'
	},
	parquet: {
		type: 'parquet',
		label: 'Parquet',
		extensions: ['.parquet'],
		colors: {
			color: 'var(--file-parquet-fg)',
			borderColor: 'var(--file-parquet-border)',
			backgroundColor: 'var(--file-parquet-bg)'
		},
		icon: FileTypeIcon,
		description: 'Apache Parquet columnar storage format'
	},
	json: {
		type: 'json',
		label: 'JSON',
		extensions: ['.json'],
		colors: {
			color: 'var(--file-json-fg)',
			borderColor: 'var(--file-json-border)',
			backgroundColor: 'var(--file-json-bg)'
		},
		icon: FileBracesCorner,
		description: 'JavaScript Object Notation'
	},
	ndjson: {
		type: 'ndjson',
		label: 'NDJSON',
		extensions: ['.ndjson', '.jsonl'],
		colors: {
			color: 'var(--file-ndjson-fg)',
			borderColor: 'var(--file-ndjson-border)',
			backgroundColor: 'var(--file-ndjson-bg)'
		},
		icon: FileBracesCorner,
		description: 'Newline-delimited JSON'
	},
	excel: {
		type: 'excel',
		label: 'Excel',
		extensions: ['.xlsx', '.xls', '.xlsm', '.xlsb'],
		colors: {
			color: 'var(--file-excel-fg)',
			borderColor: 'var(--file-excel-border)',
			backgroundColor: 'var(--file-excel-bg)'
		},
		icon: FileSpreadsheet,
		description: 'Microsoft Excel workbook'
	},
	arrow: {
		type: 'arrow',
		label: 'Arrow',
		extensions: ['.arrow', '.ipc', '.feather'],
		colors: {
			color: 'var(--file-arrow-fg)',
			borderColor: 'var(--file-arrow-border)',
			backgroundColor: 'var(--file-arrow-bg)'
		},
		icon: Database,
		description: 'Apache Arrow IPC format'
	},
	avro: {
		type: 'avro',
		label: 'Avro',
		extensions: ['.avro'],
		colors: {
			color: 'var(--file-avro-fg)',
			borderColor: 'var(--file-avro-border)',
			backgroundColor: 'var(--file-avro-bg)'
		},
		icon: FileCode,
		description: 'Apache Avro binary format'
	},
	delta: {
		type: 'delta',
		label: 'Delta',
		extensions: ['_delta_log'],
		colors: {
			color: 'var(--file-delta-fg)',
			borderColor: 'var(--file-delta-border)',
			backgroundColor: 'var(--file-delta-bg)'
		},
		icon: Layers,
		description: 'Delta Lake table format'
	},
	iceberg: {
		type: 'iceberg',
		label: 'Iceberg',
		extensions: ['metadata'],
		colors: {
			color: 'var(--file-iceberg-fg)',
			borderColor: 'var(--file-iceberg-border)',
			backgroundColor: 'var(--file-iceberg-bg)'
		},
		icon: Snowflake,
		description: 'Apache Iceberg table format'
	},
	folder: {
		type: 'folder',
		label: 'Folder',
		extensions: [],
		colors: {
			color: 'var(--file-folder-fg)',
			borderColor: 'var(--file-folder-border)',
			backgroundColor: 'var(--file-folder-bg)'
		},
		icon: FolderIcon,
		description: 'Directory or Parquet dataset'
	},
	unknown: {
		type: 'unknown',
		label: 'File',
		extensions: [],
		colors: {
			color: 'var(--file-unknown-fg)',
			borderColor: 'var(--file-unknown-border)',
			backgroundColor: 'var(--file-unknown-bg)'
		},
		icon: File,
		description: 'Unknown file type'
	}
};

/**
 * Configuration for datasource source types (non-file sources)
 * Uses the same color scheme as file types for visual consistency
 */
export const SOURCE_TYPE_REGISTRY: Record<SourceType, FileTypeConfig> = {
	file: {
		type: 'unknown',
		label: 'File',
		extensions: [],
		colors: {
			color: 'var(--source-file-fg)',
			borderColor: 'var(--source-file-border)',
			backgroundColor: 'var(--source-file-bg)'
		},
		icon: File,
		description: 'File-based datasource'
	},
	database: {
		type: 'unknown',
		label: 'Database',
		extensions: [],
		colors: {
			color: 'var(--source-database-fg)',
			borderColor: 'var(--source-database-border)',
			backgroundColor: 'var(--source-database-bg)'
		},
		icon: Database,
		description: 'Database connection'
	},
	iceberg: {
		type: 'iceberg',
		label: 'Iceberg',
		extensions: [],
		colors: {
			color: 'var(--source-iceberg-fg)',
			borderColor: 'var(--source-iceberg-border)',
			backgroundColor: 'var(--source-iceberg-bg)'
		},
		icon: Snowflake,
		description: 'Apache Iceberg table'
	},
	analysis: {
		type: 'unknown',
		label: 'Analysis',
		extensions: [],
		colors: {
			color: 'var(--source-analysis-fg)',
			borderColor: 'var(--source-analysis-border)',
			backgroundColor: 'var(--source-analysis-bg)'
		},
		icon: Layers,
		description: 'Derived analysis output'
	},
	duckdb: {
		type: 'unknown',
		label: 'DuckDB',
		extensions: [],
		colors: {
			color: 'var(--source-duckdb-fg)',
			borderColor: 'var(--source-duckdb-border)',
			backgroundColor: 'var(--source-duckdb-bg)'
		},
		icon: Database,
		description: 'DuckDB export'
	}
};

/**
 * Detect file type from a path or filename
 *
 * @param path - File path or filename
 * @param isFolder - Whether the path is a folder/directory
 * @returns The detected file type
 *
 * @example
 * ```typescript
 * detectFileType('data.parquet') // 'parquet'
 * detectFileType('data.csv') // 'csv'
 * detectFileType('/data/table/', true) // 'folder'
 * detectFileType('unknown.xyz') // 'unknown'
 * ```
 */
export function detectFileType(path: string, isFolder: boolean = false): FileType {
	if (!path) return 'unknown';

	// Handle folders first
	if (isFolder) {
		return 'folder';
	}

	// Normalize path to lowercase for case-insensitive matching
	const lowerPath = path.toLowerCase();

	// Check for Delta Lake (contains _delta_log)
	if (lowerPath.includes('_delta_log')) {
		return 'delta';
	}

	// Check for Iceberg (contains metadata folder or .metadata.json)
	if (lowerPath.includes('/metadata/') || lowerPath.endsWith('.metadata.json')) {
		return 'iceberg';
	}

	// Check all registered file types by their extensions
	for (const [fileType, config] of Object.entries(FILE_TYPE_REGISTRY)) {
		for (const ext of config.extensions) {
			if (lowerPath.endsWith(ext)) {
				return fileType as FileType;
			}
		}
	}

	// Default to unknown
	return 'unknown';
}

/**
 * Get the complete configuration for a file type
 *
 * @param fileType - The file type
 * @returns The file type configuration
 *
 * @example
 * ```typescript
 * const config = getFileTypeConfig('parquet');
 * // Returns { type: 'parquet', label: 'Parquet', colors: {...}, icon: FileTypeIcon, ... }
 * ```
 */
export function getFileTypeConfig(fileType: FileType): FileTypeConfig {
	return FILE_TYPE_REGISTRY[fileType];
}

/**
 * Get the color scheme for a file type
 *
 * @param fileType - The file type
 * @returns The color scheme
 *
 * @example
 * ```typescript
 * const colors = getFileTypeColors('csv');
 * // Returns { color: 'var(--file-csv-fg)', borderColor: '...', backgroundColor: '...' }
 * ```
 */
export function getFileTypeColors(fileType: FileType): FileTypeColors {
	return FILE_TYPE_REGISTRY[fileType].colors;
}

/**
 * Get the Lucide icon component for a file type
 *
 * @param fileType - The file type
 * @returns The Lucide icon component
 *
 * @example
 * ```typescript
 * const Icon = getFileTypeIcon('json');
 * // Use in Svelte: <Icon size={16} />
 * ```
 */
export function getFileTypeIcon(fileType: FileType): ComponentType {
	return FILE_TYPE_REGISTRY[fileType].icon;
}

/**
 * Get the display label for a file type
 *
 * @param fileType - The file type
 * @returns The display label
 *
 * @example
 * ```typescript
 * getFileTypeLabel('parquet') // 'Parquet'
 * getFileTypeLabel('ndjson') // 'NDJSON'
 * ```
 */
export function getFileTypeLabel(fileType: FileType): string {
	return FILE_TYPE_REGISTRY[fileType].label;
}

/**
 * Get the complete configuration for a datasource source type
 *
 * @param sourceType - The source type (database, api, iceberg, etc.)
 * @returns The configuration with colors, icon, and label
 *
 * @example
 * ```typescript
 * const config = getSourceTypeConfig('iceberg');
 * // Returns { type: 'iceberg', label: 'Iceberg', colors: {...}, icon: Snowflake, ... }
 * ```
 */
export function getSourceTypeConfig(sourceType: SourceType): FileTypeConfig {
	return SOURCE_TYPE_REGISTRY[sourceType];
}

export function getSourceTypeCategory(sourceType: SourceType): SourceCategory {
	return SOURCE_TYPE_CATEGORY[sourceType];
}

/**
 * Get all supported file types
 *
 * @returns Array of all file type identifiers
 *
 * @example
 * ```typescript
 * const types = getAllFileTypes();
 * // ['csv', 'parquet', 'json', 'ndjson', 'excel', ...]
 * ```
 */
export function getAllFileTypes(): FileType[] {
	return Object.keys(FILE_TYPE_REGISTRY) as FileType[];
}
