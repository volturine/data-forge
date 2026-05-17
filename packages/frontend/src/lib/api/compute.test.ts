import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

const mockTrack = vi.fn();
const mockApiRequest = vi.fn();
const mockApiBlobRequest = vi.fn();
const mockRetain = vi.fn();
const mockRelease = vi.fn();

vi.mock('$lib/utils/audit-log', () => ({
	track: (...args: unknown[]) => mockTrack(...args)
}));

vi.mock('$lib/stores/clientIdentity.svelte', () => ({
	getClientIdentity: () => ({ clientId: 'client-1', clientSignature: 'signature-1' })
}));

vi.mock('$lib/stores/namespace.svelte', () => ({
	requireNamespace: () => 'default',
	isNamespaceReady: () => true
}));

vi.mock('$lib/api/client', () => ({
	apiRequest: (...args: unknown[]) => mockApiRequest(...args),
	apiBlobRequest: (...args: unknown[]) => mockApiBlobRequest(...args)
}));

vi.mock('$lib/stores/compute-activity.svelte', () => ({
	computeActivityStore: {
		track: <T>(result: T) => {
			mockRetain();
			return result;
		},
		retain: () => {
			mockRetain();
			return () => mockRelease();
		}
	}
}));

const compute = await import('./compute');

describe('compute api activity tracking', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	afterEach(() => {
		vi.restoreAllMocks();
	});

	test('previewStepData tracks compute activity', () => {
		const result = { tag: 'preview' };
		mockApiRequest.mockReturnValue(result);

		const value = compute.previewStepData({
			target_step_id: 'step-1',
			analysis_pipeline: { analysis_id: 'analysis-1', tabs: [] }
		});

		expect(mockApiRequest).toHaveBeenCalledWith('/v1/compute/preview', {
			method: 'POST',
			body: JSON.stringify({
				target_step_id: 'step-1',
				analysis_pipeline: { analysis_id: 'analysis-1', tabs: [] }
			})
		});
		expect(mockRetain).toHaveBeenCalledTimes(1);
		expect(value).toBe(result);
	});

	test('getStepSchema tracks compute activity', () => {
		const result = { tag: 'schema' };
		mockApiRequest.mockReturnValue(result);

		const value = compute.getStepSchema({
			analysis_id: 'analysis-1',
			target_step_id: 'step-1',
			analysis_pipeline: { analysis_id: 'analysis-1', tabs: [] },
			tab_id: 'tab-1'
		});

		expect(mockApiRequest).toHaveBeenCalledWith('/v1/compute/schema', {
			method: 'POST',
			body: JSON.stringify({
				analysis_id: 'analysis-1',
				target_step_id: 'step-1',
				analysis_pipeline: { analysis_id: 'analysis-1', tabs: [] },
				tab_id: 'tab-1'
			})
		});
		expect(mockRetain).toHaveBeenCalledTimes(1);
		expect(value).toBe(result);
	});

	test('getStepRowCount tracks compute activity', () => {
		const result = { tag: 'row-count' };
		mockApiRequest.mockReturnValue(result);

		const value = compute.getStepRowCount({
			target_step_id: 'step-1',
			analysis_pipeline: { analysis_id: 'analysis-1', tabs: [] }
		});

		expect(mockApiRequest).toHaveBeenCalledWith('/v1/compute/row-count', {
			method: 'POST',
			body: JSON.stringify({
				target_step_id: 'step-1',
				analysis_pipeline: { analysis_id: 'analysis-1', tabs: [] }
			})
		});
		expect(mockRetain).toHaveBeenCalledTimes(1);
		expect(value).toBe(result);
	});

	test('downloadStep tracks compute activity', () => {
		const andThen = vi.fn();
		const result = { andThen };
		mockApiBlobRequest.mockReturnValue(result);

		compute.downloadStep({
			target_step_id: 'step-1',
			analysis_pipeline: { analysis_id: 'analysis-1', tabs: [] },
			filename: 'out',
			format: 'csv'
		});

		expect(mockApiBlobRequest).toHaveBeenCalledWith('/v1/compute/download', {
			method: 'POST',
			body: JSON.stringify({
				target_step_id: 'step-1',
				analysis_pipeline: { analysis_id: 'analysis-1', tabs: [] },
				filename: 'out',
				format: 'csv'
			})
		});
		expect(mockRetain).toHaveBeenCalledTimes(1);
		expect(andThen).toHaveBeenCalledTimes(1);
	});
});
