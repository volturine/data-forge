import { afterEach, describe, expect, test, vi } from 'vitest';
import { QueryClient } from '@tanstack/svelte-query';
import { err, okAsync, ResultAsync, type Result } from 'neverthrow';
import type { ApiError } from '$lib/api/client';
import type { StepPreviewRequest, StepPreviewResponse } from '$lib/api/compute';
import * as computeApi from '$lib/api/compute';
import { fetchPreviewQueryData } from './preview-query';

const previewStepData = vi.spyOn(computeApi, 'previewStepData');

afterEach(() => {
	previewStepData.mockReset();
});

function makePreviewRequest(): StepPreviewRequest {
	return {
		target_step_id: 'source',
		datasource_id: 'datasource-1',
		analysis_pipeline: { analysis_id: 'datasource-1', tabs: [] }
	};
}

function makePreviewResponse(): StepPreviewResponse {
	return {
		step_id: 'source',
		columns: ['value'],
		data: [{ value: 1 }],
		total_rows: 1,
		page: 1,
		page_size: 100
	};
}

describe('fetchPreviewQueryData', () => {
	test('a cancelled query is not cached as an error and can refetch when active again', async () => {
		const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
		const request = makePreviewRequest();
		const queryKey = ['datasource-preview', 'default', 'datasource-1', request] as const;
		const queryOptions = {
			queryKey,
			queryFn: ({ signal }: { signal: AbortSignal }) => fetchPreviewQueryData(request, signal)
		};
		let firstSignal: AbortSignal | undefined;
		let markRequestStarted!: () => void;
		const requestStarted = new Promise<void>((resolve) => {
			markRequestStarted = resolve;
		});
		previewStepData.mockImplementationOnce((_request, options) => {
			const signal = options?.signal;
			if (!signal) throw new Error('Query signal was not forwarded to the preview request');
			firstSignal = signal;
			markRequestStarted();
			return new ResultAsync<StepPreviewResponse, ApiError>(
				new Promise<Result<StepPreviewResponse, ApiError>>((resolve) => {
					signal.addEventListener(
						'abort',
						() =>
							resolve(
								err<StepPreviewResponse, ApiError>({
									type: 'network',
									message: 'Compute request cancelled'
								})
							),
						{ once: true }
					);
				})
			);
		});

		const cancelledFetch = client.fetchQuery(queryOptions).catch(() => undefined);
		await requestStarted;
		await client.cancelQueries({ queryKey });
		await cancelledFetch;

		expect(firstSignal?.aborted).toBe(true);
		expect(client.getQueryState(queryKey)?.status).toBe('pending');
		expect(client.getQueryState(queryKey)?.fetchStatus).toBe('idle');

		const response = makePreviewResponse();
		previewStepData.mockReturnValueOnce(okAsync(response));
		await expect(client.fetchQuery(queryOptions)).resolves.toEqual(response);
		expect(previewStepData).toHaveBeenCalledTimes(2);
		client.clear();
	});
});
