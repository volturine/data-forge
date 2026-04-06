// Compression utilities for preview data caching
// Uses native CompressionStream API (available in all modern browsers)

/**
 * Compress data using gzip and encode to base64
 * Returns null if compression fails
 */
async function collectStream(readable: ReadableStream<Uint8Array>): Promise<Uint8Array> {
	const chunks: Uint8Array[] = [];
	const reader = readable.getReader();
	while (true) {
		const { done, value } = await reader.read();
		if (done) break;
		chunks.push(value);
	}
	const out = new Uint8Array(chunks.reduce((n, c) => n + c.length, 0));
	let offset = 0;
	for (const chunk of chunks) {
		out.set(chunk, offset);
		offset += chunk.length;
	}
	return out;
}

export async function compress(data: unknown): Promise<string | null> {
	try {
		const stream = new CompressionStream('gzip');
		const writer = stream.writable.getWriter();
		writer.write(new TextEncoder().encode(JSON.stringify(data)));
		writer.close();
		return arrayBufferToBase64(await collectStream(stream.readable));
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
		const stream = new DecompressionStream('gzip');
		const writer = stream.writable.getWriter();
		await writer.write(base64ToArrayBuffer(compressed));
		await writer.close();
		const result = await collectStream(stream.readable);
		return JSON.parse(new TextDecoder().decode(result)) as T;
	} catch (err) {
		void err;
		return null;
	}
}

/**
 * Format bytes to human readable string
 */
export function formatBytes(bytes: number): string {
	if (!Number.isFinite(bytes) || bytes < 0) return '0 B';
	if (bytes === 0) return '0 B';
	const k = 1024;
	const sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
	const i = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), sizes.length - 1);
	return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

/**
 * Convert Uint8Array to base64 string
 */
function arrayBufferToBase64(buffer: Uint8Array): string {
	let binary = '';
	for (let i = 0; i < buffer.byteLength; i++) binary += String.fromCharCode(buffer[i]);
	return btoa(binary);
}

/**
 * Convert base64 string to Uint8Array
 */
function base64ToArrayBuffer(base64: string): Uint8Array<ArrayBuffer> {
	const raw = atob(base64);
	const buffer = new ArrayBuffer(raw.length);
	const view = new Uint8Array(buffer);
	for (let i = 0; i < raw.length; i++) view[i] = raw.charCodeAt(i);
	return view;
}
