import { getClientIdentity } from './clientIdentity.svelte';
import { apiRequest } from '$lib/api/client';
import { SvelteMap } from 'svelte/reactivity';

export interface LockState {
	locked: boolean;
	byMe: boolean;
	lockToken: string | null;
	expiresAt: string | null;
}

interface LockResponse {
	resource_id: string;
	client_id: string;
	lock_token: string;
	expires_at: string;
}

interface LockStatusResponse {
	locked: boolean;
	locked_by_me: boolean;
	client_id: string | null;
	expires_at: string | null;
}

// Store for lock states - resource_id -> LockState
const locks = new SvelteMap<string, LockState>();

// Track heartbeat intervals (not reactive, just for cleanup)
const heartbeatIntervals = new Map<string, number>(); // eslint-disable-line svelte/prefer-svelte-reactivity

// HEARTBEAT_INTERVAL from architecture: 10 seconds
const HEARTBEAT_INTERVAL_MS = 10000;

export function getLockState(resourceId: string): LockState {
	return locks.get(resourceId) ?? { locked: false, byMe: false, lockToken: null, expiresAt: null };
}

export function isLocked(resourceId: string): boolean {
	return getLockState(resourceId).locked;
}

export function hasLock(resourceId: string): boolean {
	const state = getLockState(resourceId);
	return state.locked && state.byMe;
}

export async function acquireLock(resourceId: string): Promise<boolean> {
	const { clientId: cid, clientSignature } = getClientIdentity();

	const result = await apiRequest<LockResponse>(
		`/v1/locks/${encodeURIComponent(resourceId)}/acquire`,
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				client_id: cid,
				client_signature: clientSignature
			})
		}
	);

	return result.match(
		(response) => {
			locks.set(resourceId, {
				locked: true,
				byMe: true,
				lockToken: response.lock_token,
				expiresAt: response.expires_at
			});
			startHeartbeat(resourceId, response.lock_token);
			return true;
		},
		(_error) => {
			// Failed to acquire - get status to update UI
			checkLockStatus(resourceId);
			return false;
		}
	);
}

export async function releaseLock(resourceId: string): Promise<boolean> {
	const state = getLockState(resourceId);
	if (!state.byMe || !state.lockToken) return false;

	const { clientId: cid } = getClientIdentity();

	stopHeartbeat(resourceId);

	const result = await apiRequest<{ status: string }>(
		`/v1/locks/${encodeURIComponent(resourceId)}/release`,
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				client_id: cid,
				lock_token: state.lockToken
			})
		}
	);

	return result.match(
		() => {
			locks.delete(resourceId);
			return true;
		},
		(_error) => {
			// Even on error, clear local state
			locks.delete(resourceId);
			return false;
		}
	);
}

export async function checkLockStatus(resourceId: string): Promise<LockState> {
	const { clientId: cid } = getClientIdentity();

	const result = await apiRequest<LockStatusResponse>(
		`/v1/locks/${encodeURIComponent(resourceId)}?client_id=${encodeURIComponent(cid)}`,
		{
			method: 'GET'
		}
	);

	return result.match(
		(status) => {
			const state: LockState = {
				locked: status.locked,
				byMe: status.locked_by_me,
				lockToken: status.locked_by_me ? getLockState(resourceId).lockToken : null,
				expiresAt: status.expires_at
			};

			if (status.locked) {
				locks.set(resourceId, state);
			} else {
				locks.delete(resourceId);
			}

			return state;
		},
		(_error) => {
			// On error, assume not locked
			locks.delete(resourceId);
			return { locked: false, byMe: false, lockToken: null, expiresAt: null };
		}
	);
}

async function sendHeartbeat(resourceId: string, lockToken: string): Promise<boolean> {
	const { clientId: cid } = getClientIdentity();

	const result = await apiRequest<LockResponse>(
		`/v1/locks/${encodeURIComponent(resourceId)}/heartbeat`,
		{
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				client_id: cid,
				lock_token: lockToken
			})
		}
	);

	return result.match(
		(response) => {
			// Update expires_at from response
			const state = getLockState(resourceId);
			if (state.byMe) {
				locks.set(resourceId, {
					...state,
					expiresAt: response.expires_at
				});
			}
			return true;
		},
		(_error) => {
			// Heartbeat failed - lock lost
			stopHeartbeat(resourceId);
			locks.delete(resourceId);
			return false;
		}
	);
}

function startHeartbeat(resourceId: string, lockToken: string) {
	stopHeartbeat(resourceId);

	const interval = window.setInterval(async () => {
		const success = await sendHeartbeat(resourceId, lockToken);
		if (!success) {
			// Lock lost, interval already stopped in sendHeartbeat
			console.warn(`Lost lock on ${resourceId}`);
		}
	}, HEARTBEAT_INTERVAL_MS);

	heartbeatIntervals.set(resourceId, interval);
}

function stopHeartbeat(resourceId: string) {
	const interval = heartbeatIntervals.get(resourceId);
	if (interval) {
		window.clearInterval(interval);
		heartbeatIntervals.delete(resourceId);
	}
}

// Release all locks on page unload
if (typeof window !== 'undefined') {
	window.addEventListener('beforeunload', () => {
		locks.forEach((state, resourceId) => {
			if (state.byMe && state.lockToken) {
				const { clientId: cid } = getClientIdentity();
				const payload = JSON.stringify({
					client_id: cid,
					lock_token: state.lockToken
				});
				const blob = new Blob([payload], { type: 'application/json' });
				navigator.sendBeacon(`/api/v1/locks/${encodeURIComponent(resourceId)}/release`, blob);
			}
		});
	});
}

// Export locks state for reactivity
export { locks };
