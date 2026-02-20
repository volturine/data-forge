const namespacePattern = /^[a-zA-Z0-9_-]+$/;

export function normalizeNamespace(value: string): string {
	const trimmed = value.trim();
	if (!trimmed) return '';
	return namespacePattern.test(trimmed) ? trimmed : '';
}
