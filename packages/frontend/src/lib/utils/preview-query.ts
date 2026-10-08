import { previewStepData, throwIfAborted } from '$lib/api/compute';
import type { StepPreviewRequest, StepPreviewResponse } from '$lib/api/compute';
import { toComputeError } from '$lib/utils/compute-error';

export async function fetchPreviewQueryData(
	request: StepPreviewRequest,
	signal: AbortSignal
): Promise<StepPreviewResponse> {
	const result = await previewStepData(request, { signal });
	throwIfAborted(signal);
	if (result.isErr()) throw toComputeError(result.error);
	return result.value;
}
