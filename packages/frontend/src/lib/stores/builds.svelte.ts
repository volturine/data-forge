import { listBuilds, type ListBuildsParams } from '$lib/api/builds';
import type { ActiveBuildSummary } from '$lib/types/build-stream';

export type BuildsStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

export class BuildsStore {
	builds = $state.raw<ActiveBuildSummary[]>([]);
	total = $state(0);
	status = $state<BuildsStatus>('disconnected');
	error = $state<string | null>(null);

	private abortController: AbortController | null = null;
	private params: ListBuildsParams | undefined;
	private inFlight = false;
	private pendingRefresh = false;

	load(params?: ListBuildsParams): void {
		if (
			sameParams(this.params, params) &&
			(this.status === 'connecting' || this.status === 'connected')
		) {
			return;
		}
		this.abortController?.abort();
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
		this.abortController?.abort();
		this.abortController = null;
		this.inFlight = false;
		this.pendingRefresh = false;
	}

	reset(): void {
		this.close();
		this.builds = [];
		this.total = 0;
		this.status = 'disconnected';
		this.error = null;
	}

	replaceBuild(next: ActiveBuildSummary): void {
		this.builds = this.builds.map((build) => (build.build_id === next.build_id ? next : build));
	}

	private fetch(): void {
		this.abortController?.abort();
		const controller = new AbortController();
		this.abortController = controller;
		this.inFlight = true;

		listBuilds(this.params, controller.signal).match(
			(response) => {
				this.finishFetch(controller);
				if (controller.signal.aborted) return;
				this.builds = response.builds;
				this.total = response.total;
				this.status = 'connected';
				this.error = null;
				if (this.pendingRefresh) {
					this.pendingRefresh = false;
					this.refresh();
				}
			},
			(err) => {
				this.finishFetch(controller);
				if (controller.signal.aborted) return;
				this.error = err.message;
				this.status = 'error';
				if (this.pendingRefresh) {
					this.pendingRefresh = false;
					this.refresh();
				}
			}
		);
	}

	private finishFetch(controller: AbortController): void {
		if (this.abortController === controller) this.abortController = null;
		this.inFlight = false;
	}
}

function sameParams(a?: ListBuildsParams, b?: ListBuildsParams): boolean {
	if (a === b) return true;
	if (!a || !b) return a === b;
	return (
		a.analysis_id === b.analysis_id &&
		a.datasource_id === b.datasource_id &&
		a.kind === b.kind &&
		a.status === b.status &&
		a.limit === b.limit &&
		a.offset === b.offset
	);
}
