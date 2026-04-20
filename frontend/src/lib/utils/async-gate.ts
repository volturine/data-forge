export interface AsyncGate {
	issue(): number;
	invalidate(): void;
	isCurrent(token: number): boolean;
}

export function createAsyncGate(): AsyncGate {
	let version = 0;

	return {
		issue() {
			version += 1;
			return version;
		},
		invalidate() {
			version += 1;
		},
		isCurrent(token: number) {
			return token === version;
		}
	};
}
