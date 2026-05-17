/**
 * Unified File Type System
 *
 * This module provides a centralized source of truth for all file type representations
 * across the application, including colors, icons, labels, and type detection.
 *
 * Usage:
 * ```typescript
 * import { detectFileType, getFileTypeConfig } from '$lib/utils/file-types';
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
	GitMerge,
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
export type SourceType = 'database' | 'iceberg' | 'file' | 'analysis' | 'derived' | 'duckdb';

export type SourceCategory = 'file' | 'database' | 'analysis' | 'derived' | 'duckdb';

export const SOURCE_TYPE_CATEGORY: Record<SourceType, SourceCategory> = {
	file: 'file',
	iceberg: 'file',
	database: 'database',
	analysis: 'analysis',
	derived: 'derived',
	duckdb: 'duckdb'
};

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
		icon: FileSpreadsheet,
		description: 'Comma-separated or Tab-separated values'
	},
	parquet: {
		type: 'parquet',
		label: 'Parquet',
		extensions: ['.parquet'],
		icon: FileTypeIcon,
		description: 'Apache Parquet columnar storage format'
	},
	json: {
		type: 'json',
		label: 'JSON',
		extensions: ['.json'],
		icon: FileBracesCorner,
		description: 'JavaScript Object Notation'
	},
	ndjson: {
		type: 'ndjson',
		label: 'NDJSON',
		extensions: ['.ndjson', '.jsonl'],
		icon: FileBracesCorner,
		description: 'Newline-delimited JSON'
	},
	excel: {
		type: 'excel',
		label: 'Excel',
		extensions: ['.xlsx', '.xls', '.xlsm', '.xlsb'],
		icon: FileSpreadsheet,
		description: 'Microsoft Excel workbook'
	},
	arrow: {
		type: 'arrow',
		label: 'Arrow',
		extensions: ['.arrow', '.ipc', '.feather'],
		icon: Database,
		description: 'Apache Arrow IPC format'
	},
	avro: {
		type: 'avro',
		label: 'Avro',
		extensions: ['.avro'],
		icon: FileCode,
		description: 'Apache Avro binary format'
	},
	delta: {
		type: 'delta',
		label: 'Delta',
		extensions: ['_delta_log'],
		icon: Layers,
		description: 'Delta Lake table format'
	},
	iceberg: {
		type: 'iceberg',
		label: 'Iceberg',
		extensions: ['metadata'],
		icon: Snowflake,
		description: 'Apache Iceberg table format'
	},
	folder: {
		type: 'folder',
		label: 'Folder',
		extensions: [],
		icon: FolderIcon,
		description: 'Directory or Parquet dataset'
	},
	unknown: {
		type: 'unknown',
		label: 'File',
		extensions: [],
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
		icon: File,
		description: 'File-based datasource'
	},
	database: {
		type: 'unknown',
		label: 'Database',
		extensions: [],
		icon: Database,
		description: 'Database connection'
	},
	iceberg: {
		type: 'iceberg',
		label: 'Iceberg',
		extensions: [],
		icon: Snowflake,
		description: 'Apache Iceberg table'
	},
	analysis: {
		type: 'unknown',
		label: 'Analysis',
		extensions: [],
		icon: Layers,
		description: 'Derived analysis output'
	},
	derived: {
		type: 'unknown',
		label: 'Derived Input',
		extensions: [],
		icon: GitMerge,
		description: 'Input derived from another tab'
	},
	duckdb: {
		type: 'unknown',
		label: 'DuckDB',
		extensions: [],
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
