import { listEngineRuns, type EngineRun, type ListEngineRunsParams } from '$lib/api/engine-runs';
import { PaginatedStore } from './paginated-store.svelte';

export class EngineRunsStore extends PaginatedStore<ListEngineRunsParams, EngineRun[]> {
	runs = $state.raw<EngineRun[]>([]);

	replaceRun(next: EngineRun): void {
		this.runs = this.runs.map((run) => (run.id === next.id ? next : run));
	}

	protected sameParams(a?: ListEngineRunsParams, b?: ListEngineRunsParams): boolean {
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

	protected fetchPage(params?: ListEngineRunsParams) {
		return listEngineRuns(params);
	}

	protected applyPage(runs: EngineRun[]): void {
		this.runs = runs;
	}

	protected clearPage(): void {
		this.runs = [];
	}
}
