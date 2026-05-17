import type { ResultAsync } from 'neverthrow';

export class ComputeActivityStore {
	private leases = $state(0);

	active = $derived(this.leases > 0);

	retain(): () => void {
		this.leases += 1;
		let released = false;
		return () => {
			if (released) return;
			released = true;
			this.leases = Math.max(0, this.leases - 1);
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
		this.leases = 0;
	}
}

export const computeActivityStore = new ComputeActivityStore();
