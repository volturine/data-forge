export type PaginatedStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

interface PaginatedError {
	message: string;
}

interface PaginatedResult<TResponse> {
	match(onOk: (response: TResponse) => void, onErr: (error: PaginatedError) => void): unknown;
}

export abstract class PaginatedStore<TParams, TResponse> {
	status = $state<PaginatedStatus>('disconnected');
	error = $state<string | null>(null);

	protected params: TParams | undefined;

	private inFlight = false;
	private pendingRefresh = false;
	private token = 0;

	load(params?: TParams): void {
		if (
			this.sameParams(this.params, params) &&
			(this.status === 'connecting' || this.status === 'connected')
		) {
			return;
		}
		this.params = params;
		this.pendingRefresh = false;
		this.status = 'connecting';
		this.error = null;
		this.fetch();
	}

	refresh(): void {
		if (this.params === undefined && this.status === 'disconnected') return;
		if (this.inFlight) {
			this.pendingRefresh = true;
			return;
		}
		this.status = 'connecting';
		this.error = null;
		this.fetch();
	}

	close(): void {
		this.token += 1;
		this.inFlight = false;
		this.pendingRefresh = false;
		this.status = 'disconnected';
		this.error = null;
	}

	reset(): void {
		this.close();
		this.clearPage();
	}

	protected abstract sameParams(a?: TParams, b?: TParams): boolean;
	protected abstract fetchPage(params?: TParams): PaginatedResult<TResponse>;
	protected abstract applyPage(response: TResponse): void;
	protected abstract clearPage(): void;

	private fetch(): void {
		const token = ++this.token;
		this.inFlight = true;

		this.fetchPage(this.params).match(
			(response) => {
				if (!this.finishFetch(token)) return;
				this.applyPage(response);
				this.status = 'connected';
				this.error = null;
				this.runPendingRefresh();
			},
			(err) => {
				if (!this.finishFetch(token)) return;
				this.error = err.message;
				this.status = 'error';
				this.runPendingRefresh();
			}
		);
	}

	private finishFetch(token: number): boolean {
		if (this.token !== token) return false;
		this.inFlight = false;
		return true;
	}

	private runPendingRefresh(): void {
		if (!this.pendingRefresh) return;
		this.pendingRefresh = false;
		this.refresh();
	}
}
