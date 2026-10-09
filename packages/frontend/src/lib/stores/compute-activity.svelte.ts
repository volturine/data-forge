import type { ResultAsync } from 'neverthrow';
import { computeWorkersStore } from '$lib/stores/compute-workers.svelte';

export class ComputeActivityStore {
	private leases = $state(0);

	active = $derived(this.leases > 0);

	retain(): () => void {
		this.leases += 1;
		if (this.leases === 1) computeWorkersStore.startStream();
		let released = false;
		return () => {
			if (released) return;
			released = true;
			this.leases = Math.max(0, this.leases - 1);
			if (this.leases === 0) computeWorkersStore.stopStream();
		};
	}

	track<T, E>(result: ResultAsync<T, E>): ResultAsync<T, E> {
		const release = this.retain();
		return result
			.map((value) => {
				release();
				return value;
			})
			.mapErr((error) => {
				release();
				return error;
			});
	}

	reset(): void {
		const hadLease = this.leases > 0;
		this.leases = 0;
		if (hadLease) computeWorkersStore.stopStream();
	}
}

export const computeActivityStore = new ComputeActivityStore();
