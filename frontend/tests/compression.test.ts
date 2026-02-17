import { describe, expect, it } from 'vitest';
import { compress, decompress, formatBytes } from '$lib/utils/compression';

describe('compression utils', () => {
	it('formatBytes returns human readable value', () => {
		expect(formatBytes(0)).toBe('0 B');
		expect(formatBytes(1024)).toContain('KB');
	});

	it('compress returns null when CompressionStream missing', async () => {
		const globalWithCompression = globalThis as { CompressionStream?: typeof CompressionStream };
		const original = globalWithCompression.CompressionStream;
		delete globalWithCompression.CompressionStream;
		const payload = { a: 1 };
		const result = await compress(payload);
		if (original) {
			globalWithCompression.CompressionStream = original;
		}
		expect(result).toBeNull();
	});

	it('decompress returns null for invalid data', async () => {
		const result = await decompress<{ a: number }>('not-base64');
		expect(result).toBeNull();
	});
});
