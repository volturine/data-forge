import { listBuilds, type ListBuildsParams } from '$lib/api/builds';
import type { ActiveBuildSummary } from '$lib/types/build-stream';

export type BuildsStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

export class BuildsStore {
	builds = $state.raw<ActiveBuildSummary[]>([]);
	total = $state(0);
	status = $state<BuildsStatus>('disconnected');
	error = $state<string | null>(null);

	private params: ListBuildsParams | undefined;
	private inFlight = false;
	private pendingRefresh = false;
	private token = 0;

	load(params?: ListBuildsParams): void {
		if (
			sameParams(this.params, params) &&
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
		this.builds = [];
		this.total = 0;
	}

	replaceBuild(next: ActiveBuildSummary): void {
		this.builds = this.builds.map((build) => (build.build_id === next.build_id ? next : build));
	}

	private fetch(): void {
		const token = ++this.token;
		this.inFlight = true;

		listBuilds(this.params).match(
			(response) => {
				if (!this.finishFetch(token)) return;
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
				if (!this.finishFetch(token)) return;
				this.error = err.message;
				this.status = 'error';
				if (this.pendingRefresh) {
					this.pendingRefresh = false;
					this.refresh();
				}
			}
		);
	}

	private finishFetch(token: number): boolean {
		if (this.token !== token) return false;
		this.inFlight = false;
		return true;
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
		a.search === b.search &&
		a.limit === b.limit &&
		a.offset === b.offset
	);
}
