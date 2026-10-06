import type { DataSource } from '$lib/types/datasource';

function recency(datasource: DataSource): number {
	const value = Date.parse(datasource.last_data_update ?? datasource.created_at);
	return Number.isFinite(value) ? value : 0;
}

/**
 * Orders datasources for picking: freshest first, and when searching, names that
 * start with the query ahead of names that merely contain it.
 */
export function rankDatasources(datasources: DataSource[], query: string): DataSource[] {
	const needle = query.trim().toLowerCase();
	const byRecency = (a: DataSource, b: DataSource) =>
		recency(b) - recency(a) || a.name.localeCompare(b.name);
	if (!needle) return [...datasources].sort(byRecency);
	const prefix: DataSource[] = [];
	const contains: DataSource[] = [];
	for (const datasource of datasources) {
		const name = datasource.name.toLowerCase();
		if (name.startsWith(needle)) prefix.push(datasource);
		else if (name.includes(needle)) contains.push(datasource);
	}
	return [...prefix.sort(byRecency), ...contains.sort(byRecency)];
}
