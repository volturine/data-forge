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
import type { ActiveBuildDetail } from '$lib/types/build-stream';
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

export function startActiveBuild(request: BuildRequest): ResultAsync<ActiveBuildDetail, ApiError> {
	return apiRequest<ActiveBuildDetail>('/v1/compute/builds', {
		method: 'POST',
		body: JSON.stringify(request)
	});
}

function isBuildDetailSnapshot(msg: BuildStreamMessage): msg is BuildDetailSnapshot {
	return isObject(msg) && (msg as Record<string, unknown>).type === 'snapshot';
}

function toBuildDetailEvent(msg: BuildStreamMessage): BuildEvent {
	if (isBuildDetailSnapshot(msg) || isErrorMessage(msg)) {
		throw new Error('Expected build event');
	}
	const event = protocolBuildEventToBuildEvent(msg);
	if (event === null) {
		throw new Error('Invalid build stream event');
	}
	return event;
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
	return createStream<BuildDetailSnapshot, BuildEvent, BuildStreamMessage>(endpoint, {
		parse: parseBuildMessage,
		isSnapshot: isBuildDetailSnapshot,
		extractSnapshot: (msg) => {
			if (!isBuildDetailSnapshot(msg)) {
				throw new Error('Expected build snapshot');
			}
			return msg;
		},
		extractEvent: toBuildDetailEvent,
		callbacks
	});
}

export function getActiveBuild(buildId: string): ResultAsync<ActiveBuildDetail, ApiError> {
	return apiRequest<ActiveBuildDetail>(`/v1/compute/builds/${buildId}`);
}
