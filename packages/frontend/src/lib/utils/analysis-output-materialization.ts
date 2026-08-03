import { isUuid } from '$lib/utils/analysis-tab';

/** Server-computed flag: datasource row exists for the reserved result_id. */
export function isOutputMaterialized(
	output: { materialized?: boolean | null } | null | undefined
): boolean {
	return output?.materialized === true;
}

/**
 * OutputNode may fetch GET /datasource/{result_id} only after materialization.
 * A reserved UUID alone is not enough.
 */
export function canQueryOutputDatasource(args: {
	resultId: string | null | undefined;
	materialized?: boolean | null;
}): boolean {
	return isUuid(args.resultId) && args.materialized === true;
}

/**
 * DatasourceNode may fetch GET /datasource/{id} for a tab input when:
 * - raw input (no analysis_tab_id): always allowed (id must be a real datasource), or
 * - derived input: only when the upstream tab's output is materialized.
 */
export function canQueryTabDatasource(args: {
	datasourceId: string | null | undefined;
	analysisTabId: string | null | undefined;
	tabs: Array<{ id: string; output?: { materialized?: boolean | null } | null }>;
}): boolean {
	if (!args.datasourceId) return false;
	if (!args.analysisTabId) return true;
	const upstream = args.tabs.find((tab) => tab.id === args.analysisTabId);
	if (!upstream) return false;
	return isOutputMaterialized(upstream.output);
}
