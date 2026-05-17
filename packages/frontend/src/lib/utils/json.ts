export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonObject | JsonArray;
export type JsonArray = JsonValue[];

export interface JsonObject {
	[key: string]: JsonValue;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function cloneJson<T>(value: T): T {
	return JSON.parse(JSON.stringify(value)) as T;
}
