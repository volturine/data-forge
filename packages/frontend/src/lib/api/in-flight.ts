import { err, ResultAsync, type Result } from 'neverthrow';

export interface SharedInFlight<T, E> {
	result: ResultAsync<T, E>;
	controller: AbortController;
	owners: Set<AbortSignal>;
	settled: boolean;
}

export function shareInFlight<T, E>(
	map: Map<string, ResultAsync<T, E>>,
	key: string,
	factory: () => ResultAsync<T, E>
): ResultAsync<T, E> {
	const existing = map.get(key);
	if (existing) return existing;
	const result = factory();
	map.set(key, result);
	void result.match(
		(value) => {
			if (map.get(key) === result) map.delete(key);
			return value;
		},
		(error) => {
			if (map.get(key) === result) map.delete(key);
			return error;
		}
	);
	return result;
}

/**
 * Share one request while it has owners, and abort the underlying request as
 * soon as the last owner is gone. Callers provide a stable lifecycle signal;
 * query-library fetch signals are intentionally not used here because their
 * observer updates can cancel and recreate a query without a component
 * actually leaving the page.
 */
export function shareInFlightWithSignal<T, E>(
	map: Map<string, SharedInFlight<T, E>>,
	key: string,
	factory: (signal: AbortSignal) => ResultAsync<T, E>,
	signal: AbortSignal,
	abortError: () => E
): ResultAsync<T, E> {
	if (signal.aborted) return new ResultAsync<T, E>(Promise.resolve(err<T, E>(abortError())));

	let entry = map.get(key);
	if (!entry) {
		const controller = new AbortController();
		const result = factory(controller.signal);
		entry = {
			result,
			controller,
			owners: new Set(),
			settled: false
		};
		map.set(key, entry);
		const current = entry;
		void result.match(
			() => {
				current.settled = true;
				if (map.get(key) === current) map.delete(key);
			},
			() => {
				current.settled = true;
				if (map.get(key) === current) map.delete(key);
			}
		);
	}

	const current = entry;
	current.owners.add(signal);
	let released = false;
	const release = (): void => {
		if (released) return;
		released = true;
		current.owners.delete(signal);
		if (current.owners.size === 0 && !current.settled && map.get(key) === current) {
			map.delete(key);
			current.controller.abort('No observers remain');
		}
	};

	const result = new ResultAsync<T, E>(
		new Promise<Result<T, E>>((resolve) => {
			const onAbort = (): void => {
				signal.removeEventListener('abort', onAbort);
				release();
				resolve(err<T, E>(abortError()));
			};
			signal.addEventListener('abort', onAbort, { once: true });
			void current.result.then((value) => {
				signal.removeEventListener('abort', onAbort);
				release();
				resolve(value);
			});
		})
	);
	return result;
}
