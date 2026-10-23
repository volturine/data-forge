import { previewStepData, throwIfAborted } from '#lib/api/compute.js';
import type { StepPreviewRequest, StepPreviewResponse } from '#lib/api/compute.js';
import { toComputeError } from '#lib/utils/compute-error.js';

export const PREVIEW_QUERY_GC_TIME = 5 * 60 * 1000;

export function createPreviewRequestCancellation(): {
	signalFor: (request: StepPreviewRequest) => AbortSignal;
	dispose: () => void;
} {
	let activeRequest: { key: string; controller: AbortController } | null = null;

	return {
		signalFor(request) {
			const key = JSON.stringify(request);
			if (activeRequest?.key === key && !activeRequest.controller.signal.aborted) {
				return activeRequest.controller.signal;
			}
			activeRequest?.controller.abort();
			const controller = new AbortController();
			activeRequest = { key, controller };
			return controller.signal;
		},
		dispose() {
			activeRequest?.controller.abort();
		}
	};
}

export function stepPreviewQueryKey(namespace: string | null, analysisId: string, stepId: string) {
	return ['step-preview', namespace, analysisId, stepId] as const;
}

export async function fetchPreviewQueryData(
	request: StepPreviewRequest,
	signal: AbortSignal,
	cancelQuery: () => void | Promise<void>
): Promise<StepPreviewResponse> {
	const handleAbort = () => {
		void cancelQuery();
	};
	if (signal.aborted) {
		handleAbort();
		throwIfAborted(signal);
	}
	signal.addEventListener('abort', handleAbort, { once: true });
	try {
		const result = await previewStepData(request, { signal });
		throwIfAborted(signal);
		if (result.isErr()) throw toComputeError(result.error);
		return result.value;
	} finally {
		signal.removeEventListener('abort', handleAbort);
	}
}
