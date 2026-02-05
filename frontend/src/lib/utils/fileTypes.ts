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
	File,
	Globe
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
export type SourceType = 'database' | 'api' | 'iceberg' | 'file' | 'duckdb';

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
			color: '#2563eb',
			borderColor: 'rgba(37, 99, 235, 0.45)',
			backgroundColor: 'rgba(37, 99, 235, 0.12)'
		},
		icon: FileSpreadsheet,
		description: 'Comma-separated or Tab-separated values'
	},
	parquet: {
		type: 'parquet',
		label: 'Parquet',
		extensions: ['.parquet'],
		colors: {
			color: '#8b5cf6',
			borderColor: 'rgba(139, 92, 246, 0.45)',
			backgroundColor: 'rgba(139, 92, 246, 0.12)'
		},
		icon: FileTypeIcon,
		description: 'Apache Parquet columnar storage format'
	},
	json: {
		type: 'json',
		label: 'JSON',
		extensions: ['.json'],
		colors: {
			color: '#0f766e',
			borderColor: 'rgba(15, 118, 110, 0.45)',
			backgroundColor: 'rgba(15, 118, 110, 0.12)'
		},
		icon: FileBracesCorner,
		description: 'JavaScript Object Notation'
	},
	ndjson: {
		type: 'ndjson',
		label: 'NDJSON',
		extensions: ['.ndjson', '.jsonl'],
		colors: {
			color: '#14b8a6',
			borderColor: 'rgba(20, 184, 166, 0.45)',
			backgroundColor: 'rgba(20, 184, 166, 0.12)'
		},
		icon: FileBracesCorner,
		description: 'Newline-delimited JSON'
	},
	excel: {
		type: 'excel',
		label: 'Excel',
		extensions: ['.xlsx', '.xls', '.xlsm', '.xlsb'],
		colors: {
			color: '#b45309',
			borderColor: 'rgba(180, 83, 9, 0.45)',
			backgroundColor: 'rgba(180, 83, 9, 0.12)'
		},
		icon: FileSpreadsheet,
		description: 'Microsoft Excel workbook'
	},
	arrow: {
		type: 'arrow',
		label: 'Arrow',
		extensions: ['.arrow', '.ipc', '.feather'],
		colors: {
			color: '#7c3aed',
			borderColor: 'rgba(124, 58, 237, 0.45)',
			backgroundColor: 'rgba(124, 58, 237, 0.12)'
		},
		icon: Database,
		description: 'Apache Arrow IPC format'
	},
	avro: {
		type: 'avro',
		label: 'Avro',
		extensions: ['.avro'],
		colors: {
			color: '#db2777',
			borderColor: 'rgba(219, 39, 119, 0.45)',
			backgroundColor: 'rgba(219, 39, 119, 0.12)'
		},
		icon: FileCode,
		description: 'Apache Avro binary format'
	},
	delta: {
		type: 'delta',
		label: 'Delta',
		extensions: ['_delta_log'],
		colors: {
			color: '#dc2626',
			borderColor: 'rgba(220, 38, 38, 0.45)',
			backgroundColor: 'rgba(220, 38, 38, 0.12)'
		},
		icon: Layers,
		description: 'Delta Lake table format'
	},
	iceberg: {
		type: 'iceberg',
		label: 'Iceberg',
		extensions: ['metadata'],
		colors: {
			color: '#1d4ed8',
			borderColor: 'rgba(29, 78, 216, 0.45)',
			backgroundColor: 'rgba(29, 78, 216, 0.12)'
		},
		icon: Snowflake,
		description: 'Apache Iceberg table format'
	},
	folder: {
		type: 'folder',
		label: 'Folder',
		extensions: [],
		colors: {
			color: '#2e7d32',
			borderColor: 'rgba(46, 125, 50, 0.4)',
			backgroundColor: 'rgba(46, 125, 50, 0.12)'
		},
		icon: FolderIcon,
		description: 'Directory or Parquet dataset'
	},
	unknown: {
		type: 'unknown',
		label: 'File',
		extensions: [],
		colors: {
			color: '#64748b',
			borderColor: 'rgba(100, 116, 139, 0.45)',
			backgroundColor: 'rgba(100, 116, 139, 0.12)'
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
			color: '#64748b',
			borderColor: 'rgba(100, 116, 139, 0.45)',
			backgroundColor: 'rgba(100, 116, 139, 0.12)'
		},
		icon: File,
		description: 'File-based datasource'
	},
	database: {
		type: 'unknown',
		label: 'Database',
		extensions: [],
		colors: {
			color: '#16a34a',
			borderColor: 'rgba(22, 163, 74, 0.45)',
			backgroundColor: 'rgba(22, 163, 74, 0.12)'
		},
		icon: Database,
		description: 'Database connection'
	},
	api: {
		type: 'unknown',
		label: 'API',
		extensions: [],
		colors: {
			color: '#ea580c',
			borderColor: 'rgba(234, 88, 12, 0.45)',
			backgroundColor: 'rgba(234, 88, 12, 0.12)'
		},
		icon: Globe,
		description: 'API endpoint'
	},
	iceberg: {
		type: 'iceberg',
		label: 'Iceberg',
		extensions: [],
		colors: {
			color: '#1d4ed8',
			borderColor: 'rgba(29, 78, 216, 0.45)',
			backgroundColor: 'rgba(29, 78, 216, 0.12)'
		},
		icon: Snowflake,
		description: 'Apache Iceberg table'
	},
	duckdb: {
		type: 'unknown',
		label: 'DuckDB',
		extensions: ['.duckdb', '.db'],
		colors: {
			color: '#f59e0b',
			borderColor: 'rgba(245, 158, 11, 0.45)',
			backgroundColor: 'rgba(245, 158, 11, 0.12)'
		},
		icon: Database,
		description: 'DuckDB database'
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
 * // Returns { color: '#2563eb', borderColor: '...', backgroundColor: '...' }
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
