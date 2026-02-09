// Hashing utilities for pipeline state comparison

/**
 * Create a deterministic hash of pipeline steps and their configs
 * Used to detect when cached preview data is stale
 */
export function hashPipeline(
	steps: Array<{
		id: string;
		type: string;
		config: Record<string, unknown>;
		depends_on?: string[];
	}>
): string {
	// Sort by ID to ensure consistent hashing
	const sorted = [...steps].sort((a, b) => a.id.localeCompare(b.id));

	// Create a minimal representation for hashing
	const hashable = sorted.map((step) => ({
		id: step.id,
		type: step.type,
		config: sortKeys(step.config),
		depends_on: step.depends_on ? [...step.depends_on].sort() : []
	}));

	const json = JSON.stringify(hashable);
	return cyrb53(json);
}

/**
 * Sort object keys recursively for consistent hashing
 */
function sortKeys(obj: unknown): unknown {
	if (obj === null || typeof obj !== 'object') {
		return obj;
	}

	if (Array.isArray(obj)) {
		return obj.map(sortKeys);
	}

	const sorted: Record<string, unknown> = {};
	const keys = Object.keys(obj as Record<string, unknown>).sort();
	for (const key of keys) {
		sorted[key] = sortKeys((obj as Record<string, unknown>)[key]);
	}
	return sorted;
}

/**
 * Fast string hashing using cyrb53 algorithm
 * Good for detecting changes, not for security
 */
function cyrb53(str: string): string {
	let h1 = 0xdeadbeef; // Initial seed
	let h2 = 0x41c6ce57; // Initial seed

	for (let i = 0; i < str.length; i++) {
		const ch = str.charCodeAt(i);
		h1 = Math.imul(h1 ^ ch, 2654435761);
		h2 = Math.imul(h2 ^ ch, 1597334677);
	}

	h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
	h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);

	// Convert to hex string
	return (h2 >>> 0).toString(16).padStart(8, '0') + (h1 >>> 0).toString(16).padStart(8, '0');
}

/**
 * Simple hash comparison
 */
export function hashesEqual(hash1: string, hash2: string): boolean {
	return hash1 === hash2;
}

/**
 * Check if cached preview is stale based on current pipeline hash
 */
export function isCacheStale(
	cachedHash: string,
	currentSteps: Array<{
		id: string;
		type: string;
		config: Record<string, unknown>;
		depends_on?: string[];
	}>
): boolean {
	const currentHash = hashPipeline(currentSteps);
	return !hashesEqual(cachedHash, currentHash);
}
