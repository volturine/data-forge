import { describe, expect, it } from 'vitest';
import {
	detectFileType,
	getFileTypeConfig,
	getFileTypeLabel,
	getFileTypeColors
} from '$lib/utils/fileTypes';

describe('fileTypes utils', () => {
	it('detects basic file extensions', () => {
		expect(detectFileType('data.csv')).toBe('csv');
		expect(detectFileType('data.parquet')).toBe('parquet');
	});

	it('detects delta and iceberg patterns', () => {
		expect(detectFileType('/tables/_delta_log/000.json')).toBe('delta');
		expect(detectFileType('/tables/metadata/00001.metadata.json')).toBe('iceberg');
	});

	it('detects folders explicitly', () => {
		expect(detectFileType('/data/exports', true)).toBe('folder');
	});

	it('falls back to unknown', () => {
		expect(detectFileType('mystery.xyz')).toBe('unknown');
	});

	it('returns config and display helpers', () => {
		const config = getFileTypeConfig('csv');
		expect(config.label).toBe('CSV');
		expect(getFileTypeLabel('parquet')).toBe('Parquet');
		expect(getFileTypeColors('json').color).toContain('var(');
	});
});
