import { cleanup, render } from '@testing-library/svelte';
import { useSvelteFlow } from '@xyflow/svelte';
import { afterEach, describe, expect, test, vi, type Mock } from 'vitest';
import LineageFlowController, { type LineageFlowApi } from './LineageFlowController.svelte';

vi.mock('@xyflow/svelte', () => ({ useSvelteFlow: vi.fn() }));

type FlowApi = Pick<ReturnType<typeof useSvelteFlow>, 'zoomIn' | 'zoomOut' | 'fitView' | 'getZoom'>;
type MockFlowApi = { [Key in keyof FlowApi]: Mock<FlowApi[Key]> };

type Deferred<T> = {
	promise: Promise<T>;
	resolve: (value: T) => void;
	reject: (reason: unknown) => void;
};

function deferred<T>(): Deferred<T> {
	let resolve!: (value: T) => void;
	let reject!: (reason: unknown) => void;
	const promise = new Promise<T>((resolvePromise, rejectPromise) => {
		resolve = resolvePromise;
		reject = rejectPromise;
	});
	return { promise, resolve, reject };
}

function createFlow(): MockFlowApi {
	return {
		zoomIn: vi.fn<FlowApi['zoomIn']>().mockResolvedValue(true),
		zoomOut: vi.fn<FlowApi['zoomOut']>().mockResolvedValue(true),
		fitView: vi.fn<FlowApi['fitView']>(),
		getZoom: vi.fn<FlowApi['getZoom']>().mockReturnValue(1)
	};
}

function mountController() {
	const flow = createFlow();
	const initialFit = deferred<boolean>();
	flow.fitView.mockReturnValue(initialFit.promise);
	// The controller only calls these four helpers from the larger flow API.
	vi.mocked(useSvelteFlow).mockReturnValue(flow as unknown as ReturnType<typeof useSvelteFlow>);
	let api: LineageFlowApi | undefined;
	const view = render(LineageFlowController, {
		props: { onready: (controllerApi) => (api = controllerApi) }
	});
	if (!api) throw new Error('Lineage flow controller did not expose its API');
	return { api, flow, initialFit, view };
}

afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});

describe('LineageFlowController', () => {
	test('waits for the initial fit before zooming and forwards zoom options and results', async () => {
		const controller = mountController();
		const options = { duration: 180 };
		const zoomResult = controller.api.zoomIn(options);

		expect(controller.flow.fitView).toHaveBeenCalledOnce();
		expect(controller.flow.fitView).toHaveBeenCalledWith();
		expect(controller.flow.zoomIn).not.toHaveBeenCalled();

		controller.initialFit.resolve(false);
		await expect(zoomResult).resolves.toBe(true);
		expect(controller.flow.zoomIn).toHaveBeenCalledOnce();
		expect(controller.flow.zoomIn).toHaveBeenCalledWith(options);
	});

	test('waits for a later fit before zooming and forwards fit options and results', async () => {
		const controller = mountController();
		controller.initialFit.resolve(true);
		await controller.initialFit.promise;

		const nextFit = deferred<boolean>();
		controller.flow.fitView.mockReturnValueOnce(nextFit.promise);
		const fitOptions = { padding: 0.2, duration: 240 };
		const fitResult = controller.api.fitView(fitOptions);
		expect(fitResult).toBe(nextFit.promise);
		expect(controller.flow.fitView).toHaveBeenNthCalledWith(2, fitOptions);

		const zoomOptions = { duration: 120 };
		controller.flow.zoomOut.mockResolvedValueOnce(false);
		const zoomResult = controller.api.zoomOut(zoomOptions);
		expect(controller.flow.zoomOut).not.toHaveBeenCalled();

		nextFit.resolve(true);
		await expect(zoomResult).resolves.toBe(false);
		expect(controller.flow.zoomOut).toHaveBeenCalledOnce();
		expect(controller.flow.zoomOut).toHaveBeenCalledWith(zoomOptions);
	});

	test('a rejected fit does not reject a waiting zoom or hide the fit error', async () => {
		const controller = mountController();
		controller.initialFit.resolve(true);
		await controller.initialFit.promise;

		const nextFit = deferred<boolean>();
		const error = new Error('fit failed');
		controller.flow.fitView.mockReturnValueOnce(nextFit.promise);
		const fitRejected = expect(controller.api.fitView()).rejects.toBe(error);
		const zoomFinished = expect(controller.api.zoomOut()).resolves.toBe(true);
		expect(controller.flow.zoomOut).not.toHaveBeenCalled();

		nextFit.reject(error);
		await Promise.all([fitRejected, zoomFinished]);
		expect(controller.flow.zoomOut).toHaveBeenCalledOnce();
	});

	test('does not refit between ordinary zoom requests', async () => {
		const controller = mountController();
		controller.initialFit.resolve(true);
		await controller.initialFit.promise;

		controller.flow.zoomIn.mockResolvedValueOnce(true);
		controller.flow.zoomOut.mockResolvedValueOnce(false);
		const zoomInResult = controller.api.zoomIn();
		expect(controller.flow.zoomIn).toHaveBeenCalledOnce();
		await expect(zoomInResult).resolves.toBe(true);
		const zoomOutResult = controller.api.zoomOut();
		expect(controller.flow.zoomOut).toHaveBeenCalledOnce();
		await expect(zoomOutResult).resolves.toBe(false);

		expect(controller.flow.fitView).toHaveBeenCalledOnce();
		expect(controller.api.getZoom()).toBe(1);
		expect(controller.flow.getZoom).toHaveBeenCalledOnce();
	});

	test('continues waiting when a newer layout fit starts during the wait', async () => {
		const controller = mountController();
		controller.initialFit.resolve(true);
		await controller.initialFit.promise;

		const firstLayoutFit = deferred<boolean>();
		const latestLayoutFit = deferred<boolean>();
		controller.flow.fitView.mockReturnValueOnce(firstLayoutFit.promise);
		controller.api.fitView();
		const zoomResult = controller.api.zoomIn();

		controller.flow.fitView.mockReturnValueOnce(latestLayoutFit.promise);
		controller.api.fitView();
		firstLayoutFit.resolve(true);
		await firstLayoutFit.promise;
		await Promise.resolve();
		expect(controller.flow.zoomIn).not.toHaveBeenCalled();

		latestLayoutFit.resolve(true);
		await expect(zoomResult).resolves.toBe(true);
		expect(controller.flow.zoomIn).toHaveBeenCalledOnce();
	});

	test('does not start zoom while a fit queued at the wait boundary is pending', async () => {
		const controller = mountController();
		let fitting = false;
		const zoomCallsWhileFitting: boolean[] = [];
		controller.flow.zoomIn.mockImplementation(() => {
			zoomCallsWhileFitting.push(fitting);
			return Promise.resolve(true);
		});
		const zoomResult = controller.api.zoomIn();
		const nextFit = deferred<boolean>();
		const fitQueued = deferred<void>();
		controller.flow.fitView.mockReturnValueOnce(nextFit.promise);

		controller.initialFit.resolve(true);
		await controller.initialFit.promise;
		queueMicrotask(() => {
			fitting = true;
			controller.api.fitView();
			fitQueued.resolve(undefined);
		});
		await fitQueued.promise;

		fitting = false;
		nextFit.resolve(true);
		await expect(zoomResult).resolves.toBe(true);
		expect(zoomCallsWhileFitting).toEqual([false]);
	});

	test('releases a zoom waiting on fit when the controller is destroyed', async () => {
		const controller = mountController();
		const zoomResult = controller.api.zoomIn();

		controller.view.unmount();
		await expect(zoomResult).resolves.toBe(false);
		expect(controller.flow.zoomIn).not.toHaveBeenCalled();
	});
});
