export function resolve(value: string): string {
	return value.startsWith('/') ? value : `/${value}`;
}
