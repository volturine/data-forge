// In dev, always use relative URLs so Vite's dev proxy handles /api
// In prod, allow overriding via VITE_API_URL, otherwise default to current host:8000
const apiEnv = import.meta.env.VITE_API_URL?.trim();

const runtimeBase =
	typeof window === 'undefined'
		? 'http://localhost:8000'
		: `${window.location.protocol}//${window.location.hostname}:8000`;

export const BASE_URL = import.meta.env.DEV ? '' : apiEnv || runtimeBase;

export class ApiError extends Error {
	constructor(
		message: string,
		public status: number,
		public statusText: string
	) {
		super(message);
		this.name = 'ApiError';
	}
}

export async function apiRequest<T>(endpoint: string, options?: RequestInit): Promise<T> {
	try {
		const response = await fetch(`${BASE_URL}${endpoint}`, {
			...options,
			headers: {
				'Content-Type': 'application/json',
				...options?.headers
			}
		});

		if (!response.ok) {
			const errorText = await response.text().catch(() => response.statusText);
			throw new ApiError(
				`API error: ${errorText || response.statusText}`,
				response.status,
				response.statusText
			);
		}

		return response.json();
	} catch (error) {
		if (error instanceof ApiError) {
			throw error;
		}
		throw new Error(`Network error: ${error instanceof Error ? error.message : 'Unknown error'}`);
	}
}

export function buildQueryString(params: Record<string, unknown>): string {
	const query = new URLSearchParams();
	Object.entries(params).forEach(([key, value]) => {
		if (value !== undefined && value !== null) {
			query.append(key, String(value));
		}
	});
	const queryString = query.toString();
	return queryString ? `?${queryString}` : '';
}
