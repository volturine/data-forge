import crypto from 'node:crypto';

export function uid(): string {
	return crypto.randomUUID().slice(0, 8);
}
