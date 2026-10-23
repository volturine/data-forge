import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

const elkMock = vi.hoisted(() => {
	const instances: Array<{ worker: Worker; layout: ReturnType<typeof vi.fn> }> = [];
	class MockElk {
		worker: Worker;
		layout = vi.fn(() => new Promise<never>(() => {}));

		constructor(options: { workerFactory?: (url?: string) => Worker }) {
			if (!options.workerFactory) throw new Error('Expected ELK worker factory.');
			this.worker = options.workerFactory();
			instances.push({ worker: this.worker, layout: this.layout });
		}
	}
	return { constructor: vi.fn(MockElk), instances };
});

vi.mock('elkjs/lib/elk-api.js', () => ({ default: elkMock.constructor }));

import { createLineageLayoutEngine } from './lineage-flow';
import type { LineageResponse } from '#lib/api/lineage.js';

class MockWorker extends EventTarget {
	static created: MockWorker[] = [];
	readonly scriptUrl: string;
	readonly terminate = vi.fn();
	onmessage: ((event: MessageEvent) => void) | null = null;
	postMessage = vi.fn();

	constructor(scriptUrl: string) {
		super();
		this.scriptUrl = scriptUrl;
		MockWorker.created.push(this);
	}
}

const response: LineageResponse = {
	nodes: [{ id: 'source:1', type: 'datasource', node_kind: 'source', name: 'Source' }],
	edges: []
};

function getWorker(index = 0): MockWorker {
	const worker = elkMock.instances[index]?.worker;
	expect(worker).toBeDefined();
	return worker as unknown as MockWorker;
}

function dispatchWorkerFailure(
	worker: MockWorker,
	type: 'error' | 'messageerror',
	message?: string
) {
	const event = new Event(type, { cancelable: true });
	if (message) Object.defineProperty(event, 'message', { value: message });
	worker.dispatchEvent(event);
}

describe('createLineageLayoutEngine', () => {
	beforeEach(() => {
		elkMock.constructor.mockClear();
		elkMock.instances.length = 0;
		MockWorker.created.length = 0;
		vi.stubGlobal('Worker', MockWorker);
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	test('keeps grid layout deterministic without creating a worker', async () => {
		vi.stubGlobal('Worker', undefined);
		const engine = createLineageLayoutEngine();

		await expect(engine.compute(response, 'grid')).resolves.toEqual(
			new Map([['source:1', { x: 80, y: 80 }]])
		);
		expect(elkMock.constructor).not.toHaveBeenCalled();
		expect(MockWorker.created).toHaveLength(0);
	});

	test.each([
		['error', 'ELK worker error: script failed to load'],
		['messageerror', 'ELK worker messageerror.']
	] as const)(
		'rejects pending layout on %s and recreates the failed worker',
		async (type, detail) => {
			const engine = createLineageLayoutEngine();
			const pending = engine.compute(response, 'vertical');
			const failedWorker = getWorker();

			expect(failedWorker.scriptUrl).toEqual(expect.any(String));
			expect(elkMock.constructor).toHaveBeenCalledWith({ workerFactory: expect.any(Function) });
			dispatchWorkerFailure(
				failedWorker,
				type,
				type === 'error' ? 'script failed to load' : undefined
			);
			await expect(pending).rejects.toThrow(detail);
			expect(failedWorker.terminate).toHaveBeenCalledOnce();

			const retry = engine.compute(response, 'horizontal');
			const retryWorker = getWorker(1);
			expect(retryWorker).not.toBe(failedWorker);

			engine.dispose();
			await expect(retry).rejects.toThrow('disposed');
			expect(retryWorker.terminate).toHaveBeenCalledOnce();
		}
	);

	test('disposal rejects pending layout and terminates the worker promptly', async () => {
		const engine = createLineageLayoutEngine();
		const pending = engine.compute(response, 'horizontal');
		const worker = getWorker();

		engine.dispose();

		expect(worker.terminate).toHaveBeenCalledOnce();
		await expect(pending).rejects.toThrow('disposed');
		await expect(engine.compute(response, 'grid')).resolves.toEqual(
			new Map([['source:1', { x: 80, y: 80 }]])
		);
		await expect(engine.compute(response, 'horizontal')).rejects.toThrow('disposed');
		expect(elkMock.constructor).toHaveBeenCalledOnce();
	});
});
