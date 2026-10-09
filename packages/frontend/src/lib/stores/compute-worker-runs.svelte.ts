import {
	listComputeWorkerRuns,
	type ComputeWorkerRun,
	type ListComputeWorkerRunsParams
} from '$lib/api/compute-worker-runs';
import { PaginatedStore } from './paginated-store.svelte';

export class ComputeWorkerRunsStore extends PaginatedStore<
	ListComputeWorkerRunsParams,
	ComputeWorkerRun[]
> {
	runs = $state.raw<ComputeWorkerRun[]>([]);

	replaceRun(next: ComputeWorkerRun): void {
		this.runs = this.runs.map((run) => (run.id === next.id ? next : run));
	}

	protected sameParams(a?: ListComputeWorkerRunsParams, b?: ListComputeWorkerRunsParams): boolean {
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

	protected fetchPage(params?: ListComputeWorkerRunsParams) {
		return listComputeWorkerRuns(params);
	}

	protected applyPage(runs: ComputeWorkerRun[]): void {
		this.runs = runs;
	}

	protected clearPage(): void {
		this.runs = [];
	}
}
