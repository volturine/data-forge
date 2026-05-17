import { describe, test, expect } from 'vitest';
import {
	detectFileType,
	getFileTypeConfig,
	getSourceTypeConfig,
	getSourceTypeCategory,
	getAllFileTypes,
	FILE_TYPE_REGISTRY,
	SOURCE_TYPE_REGISTRY,
	SOURCE_TYPE_CATEGORY
} from './file-types';
import type { FileType, SourceType } from './file-types';

describe('detectFileType', () => {
	test('returns unknown for empty string', () => {
		expect(detectFileType('')).toBe('unknown');
	});

	test('detects csv extension', () => {
		expect(detectFileType('data.csv')).toBe('csv');
	});

	test('detects tsv as csv', () => {
		expect(detectFileType('data.tsv')).toBe('csv');
	});

	test('detects parquet', () => {
		expect(detectFileType('table.parquet')).toBe('parquet');
	});

	test('detects json', () => {
		expect(detectFileType('config.json')).toBe('json');
	});

	test('detects ndjson', () => {
		expect(detectFileType('stream.ndjson')).toBe('ndjson');
	});

	test('detects jsonl as ndjson', () => {
		expect(detectFileType('logs.jsonl')).toBe('ndjson');
	});

	test('detects xlsx as excel', () => {
		expect(detectFileType('report.xlsx')).toBe('excel');
	});

	test('detects xls as excel', () => {
		expect(detectFileType('old.xls')).toBe('excel');
	});

	test('detects xlsm as excel', () => {
		expect(detectFileType('macro.xlsm')).toBe('excel');
	});

	test('detects xlsb as excel', () => {
		expect(detectFileType('binary.xlsb')).toBe('excel');
	});

	test('detects arrow ipc', () => {
		expect(detectFileType('data.arrow')).toBe('arrow');
	});

	test('detects ipc extension', () => {
		expect(detectFileType('data.ipc')).toBe('arrow');
	});

	test('detects feather extension', () => {
		expect(detectFileType('data.feather')).toBe('arrow');
	});

	test('detects avro', () => {
		expect(detectFileType('schema.avro')).toBe('avro');
	});

	test('detects delta lake by _delta_log path', () => {
		expect(detectFileType('/data/_delta_log/00000.json')).toBe('delta');
	});

	test('detects iceberg by /metadata/ path', () => {
		expect(detectFileType('/warehouse/metadata/v1.json')).toBe('iceberg');
	});

	test('detects iceberg by .metadata.json suffix', () => {
		expect(detectFileType('table.metadata.json')).toBe('iceberg');
	});

	test('returns folder when isFolder is true', () => {
		expect(detectFileType('/data/table/', true)).toBe('folder');
	});

	test('folder takes precedence over extension', () => {
		expect(detectFileType('/data/output.csv/', true)).toBe('folder');
	});

	test('returns unknown for unrecognized extension', () => {
		expect(detectFileType('readme.txt')).toBe('unknown');
	});

	test('is case-insensitive', () => {
		expect(detectFileType('DATA.CSV')).toBe('csv');
		expect(detectFileType('TABLE.PARQUET')).toBe('parquet');
	});
});

describe('getFileTypeConfig', () => {
	test('returns config for known file type', () => {
		const cfg = getFileTypeConfig('parquet');
		expect(cfg.type).toBe('parquet');
		expect(cfg.label).toBe('Parquet');
		expect(cfg.extensions).toContain('.parquet');
	});

	test('returns config for unknown type', () => {
		const cfg = getFileTypeConfig('unknown');
		expect(cfg.type).toBe('unknown');
		expect(cfg.label).toBe('File');
	});

	test('every registry entry has required fields', () => {
		for (const [key, cfg] of Object.entries(FILE_TYPE_REGISTRY)) {
			expect(cfg.type).toBe(key);
			expect(cfg.label).toBeTruthy();
			expect(cfg.icon).toBeDefined();
			expect(cfg.description).toBeTruthy();
			expect(Array.isArray(cfg.extensions)).toBe(true);
		}
	});
});

describe('getSourceTypeConfig', () => {
	test('returns config for database source', () => {
		const cfg = getSourceTypeConfig('database');
		expect(cfg.label).toBe('Database');
	});

	test('returns config for iceberg source', () => {
		const cfg = getSourceTypeConfig('iceberg');
		expect(cfg.label).toBe('Iceberg');
	});

	test('returns config for derived source', () => {
		const cfg = getSourceTypeConfig('derived');
		expect(cfg.label).toBe('Derived Input');
		expect(cfg.description).toBe('Input derived from another tab');
	});

	test('every source type registry entry has required fields', () => {
		for (const cfg of Object.values(SOURCE_TYPE_REGISTRY)) {
			expect(cfg.label).toBeTruthy();
			expect(cfg.icon).toBeDefined();
			expect(cfg.description).toBeTruthy();
		}
	});
});

describe('getSourceTypeCategory', () => {
	const expected: Record<SourceType, string> = {
		file: 'file',
		iceberg: 'file',
		database: 'database',
		analysis: 'analysis',
		derived: 'derived',
		duckdb: 'duckdb'
	};

	for (const [source, category] of Object.entries(expected)) {
		test(`${source} maps to ${category}`, () => {
			expect(getSourceTypeCategory(source as SourceType)).toBe(category);
		});
	}

	test('SOURCE_TYPE_CATEGORY covers all source types', () => {
		const sourceTypes: SourceType[] = [
			'file',
			'iceberg',
			'database',
			'analysis',
			'derived',
			'duckdb'
		];
		for (const st of sourceTypes) {
			expect(SOURCE_TYPE_CATEGORY[st]).toBeDefined();
		}
	});
});

describe('getAllFileTypes', () => {
	test('returns all types from registry', () => {
		const types = getAllFileTypes();
		const registryKeys = Object.keys(FILE_TYPE_REGISTRY) as FileType[];
		expect(types).toEqual(registryKeys);
	});

	test('includes csv, parquet, json, and unknown', () => {
		const types = getAllFileTypes();
		expect(types).toContain('csv');
		expect(types).toContain('parquet');
		expect(types).toContain('json');
		expect(types).toContain('unknown');
	});
});
