import {
	getAnalysisWithHeaders,
	type AnalysisDetail,
	type AnalysisDetailResult
} from '$lib/api/analysis';

export const analysisQueryKey = (analysisId: string) => ['analysis', analysisId] as const;

export async function fetchAnalysis(
	analysisId: string,
	previousEtag?: string
): Promise<AnalysisDetailResult> {
	const result = await getAnalysisWithHeaders(analysisId, previousEtag);
	if (result.isErr()) {
		throw new Error(result.error.message);
	}
	return result.value;
}

export type { AnalysisDetail };
