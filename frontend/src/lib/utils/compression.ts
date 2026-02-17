// Compression utilities for preview data caching
// Uses native CompressionStream API (available in all modern browsers)

/**
 * Compress data using gzip and encode to base64
 * Returns null if compression fails
 */
export async function compress(data: unknown): Promise<string | null> {
	try {
		const jsonString = JSON.stringify(data);
		const encoder = new TextEncoder();
		const uint8Array = encoder.encode(jsonString);

		const compressedStream = new CompressionStream('gzip');
		const writer = compressedStream.writable.getWriter();
		writer.write(uint8Array);
		writer.close();

		const reader = compressedStream.readable.getReader();
		const chunks: Uint8Array[] = [];

		while (true) {
			const { done, value } = await reader.read();
			if (done) break;
			chunks.push(value);
		}

		// Combine chunks
		const totalLength = chunks.reduce((acc, chunk) => acc + chunk.length, 0);
		const result = new Uint8Array(totalLength);
		let offset = 0;
		for (const chunk of chunks) {
			result.set(chunk, offset);
			offset += chunk.length;
		}

		// Convert to base64
		return arrayBufferToBase64(result);
	} catch (err) {
		void err;
		return null;
	}
}

/**
 * Decompress data from base64 and parse JSON
 * Returns null if decompression fails
 */
export async function decompress<T>(compressed: string): Promise<T | null> {
	try {
		const uint8Array = base64ToArrayBuffer(compressed);

		const decompressedStream = new DecompressionStream('gzip');
		const writer = decompressedStream.writable.getWriter();
		await writer.write(uint8Array as unknown as BufferSource);
		await writer.close();

		const reader = decompressedStream.readable.getReader();
		const chunks: Uint8Array[] = [];

		while (true) {
			const { done, value } = await reader.read();
			if (done) break;
			chunks.push(value);
		}

		// Combine chunks
		const totalLength = chunks.reduce((acc, chunk) => acc + chunk.length, 0);
		const result = new Uint8Array(totalLength);
		let offset = 0;
		for (const chunk of chunks) {
			result.set(chunk, offset);
			offset += chunk.length;
		}

		// Decode and parse
		const decoder = new TextDecoder();
		const jsonString = decoder.decode(result);
		return JSON.parse(jsonString) as T;
	} catch (err) {
		void err;
		return null;
	}
}

/**
 * Format bytes to human readable string
 */
export function formatBytes(bytes: number): string {
	if (bytes === 0) return '0 B';
	const k = 1024;
	const sizes = ['B', 'KB', 'MB', 'GB'];
	const i = Math.floor(Math.log(bytes) / Math.log(k));
	return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

/**
 * Convert Uint8Array to base64 string
 */
function arrayBufferToBase64(buffer: Uint8Array): string {
	const bytes = new Uint8Array(buffer);
	let binary = '';
	for (let i = 0; i < bytes.byteLength; i++) {
		binary += String.fromCharCode(bytes[i]);
	}
	return btoa(binary);
}

/**
 * Convert base64 string to Uint8Array
 */
function base64ToArrayBuffer(base64: string): Uint8Array {
	const binary = atob(base64);
	const bytes = new Uint8Array(binary.length);
	for (let i = 0; i < binary.length; i++) {
		bytes[i] = binary.charCodeAt(i);
	}
	return bytes;
}
