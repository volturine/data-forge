export function nextAnalysisName(base: string, existingNames: Iterable<string>): string {
	const existing = new Set(Array.from(existingNames, (n) => n.trim().toLowerCase()));
	if (!existing.has(base.trim().toLowerCase())) return base;
	let suffix = 2;
	while (existing.has(`${base.trim().toLowerCase()} (${suffix})`)) suffix += 1;
	return `${base} (${suffix})`;
}
