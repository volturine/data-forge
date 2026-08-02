export function selectionOpacity(selected: Set<string>, key: string, dimOpacity: number): number {
	return selected.size === 0 || selected.has(key) ? 1 : dimOpacity;
}

export function toggleSelection(selected: Set<string>, key: string, multi: boolean): void {
	if (!multi) selected.clear();
	if (selected.has(key)) selected.delete(key);
	else selected.add(key);
}

export function toggleSeries(hidden: Set<string>, series: string): void {
	if (hidden.has(series)) hidden.delete(series);
	else hidden.add(series);
}

export function isolateSeries(hidden: Set<string>, series: string, allSeries: string[]): void {
	hidden.clear();
	for (const item of allSeries) if (item !== series) hidden.add(item);
}
