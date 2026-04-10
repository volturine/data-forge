import {
	connectEngineRunsStream,
	type EngineRun,
	type ListEngineRunsParams
} from '$lib/api/engine-runs';

export type EngineRunsStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

export class EngineRunsStore {
	runs = $state<EngineRun[]>([]);
	status = $state<EngineRunsStatus>('disconnected');
	error = $state<string | null>(null);

	private connection: { close: () => void } | null = null;

	start(params?: ListEngineRunsParams): void {
		this.close();
		this.status = 'connecting';
		this.error = null;
		this.connection = connectEngineRunsStream(params, {
			onSnapshot: (runs: EngineRun[]) => {
				this.runs = runs;
				this.status = 'connected';
				this.error = null;
			},
			onError: (msg: string) => {
				this.error = msg;
				this.status = 'error';
			},
			onClose: () => {
				if (this.status !== 'error') {
					this.status = 'disconnected';
				}
			}
		});
	}

	close(): void {
		this.connection?.close();
		this.connection = null;
	}

	reset(): void {
		this.close();
		this.runs = [];
		this.status = 'disconnected';
		this.error = null;
	}
}
