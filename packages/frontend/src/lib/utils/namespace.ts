/** Namespace name == S3 bucket. No rewriting — invalid names are rejected. */
const namespacePattern = /^[a-z0-9][a-z0-9_-]{1,61}[a-z0-9]$/;

export const NAMESPACE_NAME_RULES =
	'3–63 characters; lowercase letters, digits, hyphens, and underscores; must start and end with a letter or digit. Used as the S3 bucket name with no rewriting.';

export function isValidNamespace(value: string): boolean {
	const trimmed = value.trim();
	if (!trimmed || trimmed.length < 3 || trimmed.length > 63) return false;
	if (trimmed.includes('..') || trimmed.startsWith('xn--')) return false;
	return namespacePattern.test(trimmed);
}

export function normalizeNamespace(value: string): string {
	const trimmed = value.trim();
	if (!trimmed) return '';
	return isValidNamespace(trimmed) ? trimmed : '';
}
