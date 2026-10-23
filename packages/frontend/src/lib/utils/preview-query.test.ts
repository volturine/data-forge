import { afterEach, describe, expect, test, vi } from 'vitest';
import { CancelledError, QueryClient, QueryObserver } from '@tanstack/svelte-query';
import { err, okAsync, ResultAsync, type Result } from 'neverthrow';
import type { ApiError } from '#lib/api/client.js';
import type { StepPreviewRequest, StepPreviewResponse } from '#lib/api/compute.js';
import * as computeApi from '#lib/api/compute.js';
import {
	createPreviewRequestCancellation,
	fetchPreviewQueryData,
	PREVIEW_QUERY_GC_TIME,
	stepPreviewQueryKey
} from './preview-query';

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

describe('stepPreviewQueryKey', () => {
	test('returns a stable prefix for one step across all command variants', () => {
		expect(stepPreviewQueryKey('default', 'analysis-1', 'view-1')).toEqual([
			'step-preview',
			'default',
			'analysis-1',
			'view-1'
		]);
	});

	test('keeps different target steps in separate invalidation prefixes', () => {
		expect(stepPreviewQueryKey('default', 'analysis-1', 'view-1')).not.toEqual(
			stepPreviewQueryKey('default', 'analysis-1', 'view-2')
		);
	});
});

describe('createPreviewRequestCancellation', () => {
	test('reuses a signal for the same command and aborts it when the command changes', () => {
		const cancellation = createPreviewRequestCancellation();
		const request = makePreviewRequest();
		const firstSignal = cancellation.signalFor(request);

		expect(cancellation.signalFor(makePreviewRequest())).toBe(firstSignal);

		const nextSignal = cancellation.signalFor({ ...request, target_step_id: 'view-1' });
		expect(firstSignal.aborted).toBe(true);
		expect(nextSignal.aborted).toBe(false);
		cancellation.dispose();
	});

	test('recreates an aborted signal for the same command and aborts it on disposal', () => {
		const cancellation = createPreviewRequestCancellation();
		const request = makePreviewRequest();
		const firstSignal = cancellation.signalFor(request);

		cancellation.dispose();
		expect(firstSignal.aborted).toBe(true);

		const nextSignal = cancellation.signalFor(request);
		expect(nextSignal).not.toBe(firstSignal);
		expect(nextSignal.aborted).toBe(false);

		cancellation.dispose();
		expect(nextSignal.aborted).toBe(true);
	});
});

describe('preview query cache retention', () => {
	test('keeps observed data and garbage-collects it after the inactive retention window', async () => {
		vi.useFakeTimers();
		const client = new QueryClient();
		const response = makePreviewResponse();
		const queryKey = ['step-preview', 'default', 'analysis-1', 'view-1'] as const;
		const observer = new QueryObserver(client, {
			queryKey,
			queryFn: async () => response,
			staleTime: Infinity,
			gcTime: PREVIEW_QUERY_GC_TIME
		});
		client.setQueryData(queryKey, response);
		const unsubscribe = observer.subscribe(() => {});

		try {
			await vi.advanceTimersByTimeAsync(PREVIEW_QUERY_GC_TIME);
			expect(client.getQueryData(queryKey)).toEqual(response);

			unsubscribe();
			await vi.advanceTimersByTimeAsync(PREVIEW_QUERY_GC_TIME - 1);
			expect(client.getQueryData(queryKey)).toEqual(response);

			await vi.advanceTimersByTimeAsync(1);
			expect(client.getQueryData(queryKey)).toBeUndefined();
		} finally {
			unsubscribe();
			client.clear();
			vi.useRealTimers();
		}
	});
});

describe('fetchPreviewQueryData', () => {
	test('a cancelled query is not cached as an error and can refetch when active again', async () => {
		const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
		const request = makePreviewRequest();
		const queryKey = ['datasource-preview', 'default', 'datasource-1', request] as const;
		let controller = new AbortController();
		const queryOptions = {
			queryKey,
			queryFn: () =>
				fetchPreviewQueryData(request, controller.signal, () =>
					client.cancelQueries({ queryKey, exact: true })
				)
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

		const cancelledFetch = client.fetchQuery(queryOptions).then(
			() => null,
			(error: unknown) => error
		);
		await requestStarted;
		controller.abort();
		const cancellationError = await cancelledFetch;

		expect(firstSignal?.aborted).toBe(true);
		expect(cancellationError).toBeInstanceOf(CancelledError);
		expect(client.getQueryState(queryKey)?.status).toBe('pending');
		expect(client.getQueryState(queryKey)?.fetchStatus).toBe('idle');

		controller = new AbortController();
		const response = makePreviewResponse();
		previewStepData.mockReturnValueOnce(okAsync(response));
		await expect(client.fetchQuery(queryOptions)).resolves.toEqual(response);
		expect(previewStepData).toHaveBeenCalledTimes(2);
		client.clear();
	});
});
