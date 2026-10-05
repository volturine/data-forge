export function nextAnalysisName(base: string, existingNames: Iterable<string>): string {
	const existing = new Set(existingNames);
	if (!existing.has(base)) return base;
	let suffix = 2;
	while (existing.has(`${base} (${suffix})`)) suffix += 1;
	return `${base} (${suffix})`;
}
