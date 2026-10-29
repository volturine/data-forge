export type QueryParams = Record<string, string | number | boolean | null | undefined>;

/** Appends the non-empty params to `path`; `false`, `null`, `''` and `undefined` are omitted. */
export function withQuery(path: string, params: QueryParams): string {
	const query = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (value === undefined || value === null || value === '' || value === false) continue;
		query.set(key, String(value));
	}
	const qs = query.toString();
	return qs ? `${path}?${qs}` : path;
}
