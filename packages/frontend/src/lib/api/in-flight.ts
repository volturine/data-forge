import type { ResultAsync } from 'neverthrow';

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
