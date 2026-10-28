import { untrack } from 'svelte';
import { listBuilds, type ListBuildsParams } from '#lib/api/builds.js';
import type { BuildRunListResponse, BuildRunSummary } from '#lib/types/build-stream.js';

export type BuildsStoreStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

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

export class BuildsStore {
	status = $state<BuildsStoreStatus>('disconnected');
	error = $state<string | null>(null);
	builds = $state.raw<BuildRunSummary[]>([]);
	total = $state(0);

	private params: ListBuildsParams | undefined;
	private inFlight = false;
	private pendingRefresh = false;
	private pendingSilent = false;
	private token = 0;

	replaceBuild(next: BuildRunSummary): void {
		this.builds = this.builds.map((build) => (build.build_id === next.build_id ? next : build));
	}

	load(params?: ListBuildsParams): void {
		const alreadyActive = untrack(
			() =>
				sameParams(this.params, params) &&
				(this.status === 'connecting' || this.status === 'connected')
		);
		if (alreadyActive) {
			return;
		}
		this.params = params;
		this.pendingRefresh = false;
		this.pendingSilent = false;
		this.status = 'connecting';
		this.error = null;
		this.fetch();
	}

	refresh(): void {
		this.pendingSilent = false;
		this.refreshInternal(false);
	}

	/**
	 * Refetch without blanking the current page: keeps showing the existing
	 * rows (and spinner-free status) until the new response lands, then swaps
	 * them in. Use for background polling so a refresh never flashes a spinner.
	 */
	silentRefresh(): void {
		this.refreshInternal(true);
	}

	private refreshInternal(silent: boolean): void {
		if (this.params === undefined && this.status === 'disconnected') return;
		if (this.inFlight) {
			this.pendingRefresh = true;
			this.pendingSilent = silent;
			return;
		}
		if (!silent) {
			this.status = 'connecting';
		}
		this.error = null;
		this.fetch();
	}

	close(): void {
		this.token += 1;
		this.inFlight = false;
		this.pendingRefresh = false;
		this.pendingSilent = false;
		this.status = 'disconnected';
		this.error = null;
	}

	reset(): void {
		this.close();
		this.builds = [];
		this.total = 0;
	}

	private fetch(): void {
		const token = ++this.token;
		this.inFlight = true;

		listBuilds(this.params).match(
			(response: BuildRunListResponse) => {
				if (!this.finishFetch(token)) return;
				this.builds = response.builds;
				this.total = response.total;
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
		const silent = this.pendingSilent;
		this.pendingSilent = false;
		this.refreshInternal(silent);
	}
}
