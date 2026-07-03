import { listBuilds, type ListBuildsParams } from '$lib/api/builds';
import type { ActiveBuildSummary } from '$lib/types/build-stream';
import { PaginatedStore, type PaginatedStatus } from './paginated-store.svelte';

export type BuildsStatus = PaginatedStatus;

interface BuildsPage {
	builds: ActiveBuildSummary[];
	total: number;
}

export class BuildsStore extends PaginatedStore<ListBuildsParams, BuildsPage> {
	builds = $state.raw<ActiveBuildSummary[]>([]);
	total = $state(0);

	replaceBuild(next: ActiveBuildSummary): void {
		this.builds = this.builds.map((build) => (build.build_id === next.build_id ? next : build));
	}

	protected sameParams(a?: ListBuildsParams, b?: ListBuildsParams): boolean {
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

	protected fetchPage(params?: ListBuildsParams) {
		return listBuilds(params);
	}

	protected applyPage(response: BuildsPage): void {
		this.builds = response.builds;
		this.total = response.total;
	}

	protected clearPage(): void {
		this.builds = [];
		this.total = 0;
	}
}
