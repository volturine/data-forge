import type { BuildRequest } from './compute';
import { apiRequest } from './client';
import { createStream, type StreamHandle } from './websocket';
import type { BuildEventJson } from '$lib/protocol/dataforge_protocol/compute_pb';
import {
	isProtocolBuildEvent,
	protocolBuildEventToBuildEvent
} from '$lib/types/protocol-build-stream';
import type {
	BuildEvent,
	BuildDetailSnapshot,
	BuildWebsocketErrorMessage
} from '$lib/types/build-stream';
import type { BuildRunDetail } from '$lib/types/build-stream';
import type { ResultAsync } from 'neverthrow';
import type { ApiError } from './client';

export type BuildStreamMessage = BuildDetailSnapshot | BuildWebsocketErrorMessage | BuildEventJson;

export interface BuildStreamCallbacks {
	onSnapshot: (snapshot: BuildDetailSnapshot) => void;
	onEvent: (event: BuildEvent) => void;
	onError: (error: string) => void;
	onClose: () => void;
}

function isObject(value: unknown): value is Record<string, unknown> {
	return typeof value === 'object' && value !== null;
}

function isSnapshotMessage(value: unknown): value is BuildDetailSnapshot {
	if (!isObject(value)) return false;
	return value.type === 'snapshot' && isObject(value.build);
}

function isErrorMessage(value: unknown): value is BuildWebsocketErrorMessage {
	if (!isObject(value)) return false;
	return value.type === 'error' && typeof value.error === 'string';
}

function parseBuildMessage(data: string): BuildStreamMessage | null {
	try {
		const parsed: unknown = JSON.parse(data);
		if (!isObject(parsed)) {
			return { type: 'error', error: 'Invalid build stream message', status_code: 500 };
		}
		if (isSnapshotMessage(parsed)) return parsed;
		if (isErrorMessage(parsed)) return parsed;
		if (isProtocolBuildEvent(parsed)) return parsed;
		return { type: 'error', error: 'Invalid build stream message', status_code: 500 };
	} catch {
		return { type: 'error', error: 'Invalid build stream message', status_code: 500 };
	}
}

export function startRuntimeBuild(request: BuildRequest): ResultAsync<BuildRunDetail, ApiError> {
	return apiRequest<BuildRunDetail>('/v1/compute/builds', {
		method: 'POST',
		body: JSON.stringify(request)
	});
}

function isBuildDetailSnapshot(msg: BuildStreamMessage): msg is BuildDetailSnapshot {
	return isObject(msg) && (msg as Record<string, unknown>).type === 'snapshot';
}

function toBuildDetailEvent(msg: BuildStreamMessage): BuildEvent | null {
	if (isBuildDetailSnapshot(msg) || isErrorMessage(msg)) {
		return null;
	}
	return protocolBuildEventToBuildEvent(msg);
}

export function connectBuildDetailStream(
	buildId: string,
	lastSequence: number,
	callbacks: BuildStreamCallbacks
): StreamHandle {
	const endpoint =
		lastSequence > 0
			? `/v1/compute/ws/builds/${buildId}?last_sequence=${lastSequence}`
			: `/v1/compute/ws/builds/${buildId}`;
	return createStream<BuildDetailSnapshot | null, BuildEvent | null, BuildStreamMessage>(endpoint, {
		parse: parseBuildMessage,
		isSnapshot: isBuildDetailSnapshot,
		extractSnapshot: (msg) => (isBuildDetailSnapshot(msg) ? msg : null),
		extractEvent: (msg) => {
			const event = toBuildDetailEvent(msg);
			if (event === null) {
				callbacks.onError('Invalid build stream event');
				return null;
			}
			return event;
		},
		callbacks: {
			onSnapshot: (snapshot) => {
				if (snapshot !== null) callbacks.onSnapshot(snapshot);
			},
			onEvent: (event) => {
				if (event !== null) callbacks.onEvent(event);
			},
			onError: callbacks.onError,
			onClose: callbacks.onClose
		}
	});
}

export function getRuntimeBuild(buildId: string): ResultAsync<BuildRunDetail, ApiError> {
	return apiRequest<BuildRunDetail>(`/v1/compute/builds/${buildId}`);
}
