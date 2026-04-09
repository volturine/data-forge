import { buildWebsocketUrl } from './websocket';
import type { EngineRun, ListEngineRunsParams } from './engine-runs';

export type EngineRunsStreamMessage =
	| { type: 'snapshot'; runs: EngineRun[] }
	| { type: 'update'; run: EngineRun };

export interface EngineRunsStreamCallbacks {
	onSnapshot: (runs: EngineRun[]) => void;
	onUpdate: (run: EngineRun) => void;
	onError: (error: string) => void;
	onClose: () => void;
}

function parseMessage(data: string): EngineRunsStreamMessage | null {
	try {
		return JSON.parse(data) as EngineRunsStreamMessage;
	} catch {
		return null;
	}
}

function buildParamsQuery(params: ListEngineRunsParams): string {
	const query = new URLSearchParams();
	if (params.analysis_id) query.set('analysis_id', params.analysis_id);
	if (params.datasource_id) query.set('datasource_id', params.datasource_id);
	if (params.kind) query.set('kind', params.kind);
	if (params.status) query.set('status', params.status);
	if (params.limit !== undefined) query.set('limit', String(params.limit));
	if (params.offset !== undefined) query.set('offset', String(params.offset));
	const qs = query.toString();
	return qs ? `?${qs}` : '';
}

export function connectEngineRunsStream(
	params: ListEngineRunsParams,
	callbacks: EngineRunsStreamCallbacks
): { close: () => void } {
	const suffix = buildParamsQuery(params);
	const url = buildWebsocketUrl(`/v1/engine-runs/ws${suffix}`);
	const socket = new WebSocket(url);

	socket.addEventListener('message', (event) => {
		const msg = parseMessage(event.data as string);
		if (!msg) return;
		if (msg.type === 'snapshot') {
			callbacks.onSnapshot(msg.runs);
			return;
		}
		if (msg.type === 'update') {
			callbacks.onUpdate(msg.run);
		}
	});

	socket.addEventListener('error', () => {
		callbacks.onError('WebSocket connection failed');
	});

	socket.addEventListener('close', (event) => {
		if (event.code !== 1000 && event.code !== 1005) {
			callbacks.onError(event.reason || `Connection closed (code ${event.code})`);
		}
		callbacks.onClose();
	});

	return {
		close() {
			if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
				socket.close(1000);
			}
		}
	};
}
