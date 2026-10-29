import type { BuildRequest } from './compute';
import { apiRequest } from './client';
import {
	createStream,
	isErrorMessage,
	type StreamErrorMessage,
	type StreamHandle
} from './websocket';
import type { BuildEventJson } from '#lib/protocol/dataforge_protocol/compute_pb.js';
import {
	isProtocolBuildEvent,
	protocolBuildEventToBuildEvent
} from '#lib/types/protocol-build-stream.js';
import type { BuildEvent, BuildDetailSnapshot } from '#lib/types/build-stream.js';
import type { BuildRunDetail, BuildRunSummary } from '#lib/types/build-stream.js';
import type { ResultAsync } from 'neverthrow';
import type { ApiError } from './client';
import { isRecord } from '#lib/utils/json.js';

export type BuildStreamMessage = BuildDetailSnapshot | StreamErrorMessage | BuildEventJson;

export type BuildListSnapshotMessage = {
	type: 'snapshot';
	builds: BuildRunSummary[];
};

export type BuildListStreamMessage = BuildListSnapshotMessage | StreamErrorMessage;

export interface BuildStreamCallbacks {
	onSnapshot: (snapshot: BuildDetailSnapshot) => void;
	onEvent: (event: BuildEvent) => void;
	onError: (error: string) => void;
	onClose: () => void;
}

const INVALID_BUILD_MESSAGE = {
	type: 'error',
	error: 'Invalid build stream message',
	status_code: 500
} satisfies StreamErrorMessage & { status_code: number };

function isSnapshotMessage(value: unknown): value is BuildDetailSnapshot {
	return isRecord(value) && value.type === 'snapshot' && isRecord(value.build);
}

function parseBuildMessage(data: string): BuildStreamMessage | null {
	try {
		const parsed: unknown = JSON.parse(data);
		if (!isRecord(parsed)) return INVALID_BUILD_MESSAGE;
		if (isSnapshotMessage(parsed)) return parsed;
		if (isErrorMessage(parsed)) return parsed;
		if (isProtocolBuildEvent(parsed)) return parsed;
		return INVALID_BUILD_MESSAGE;
	} catch {
		return INVALID_BUILD_MESSAGE;
	}
}

export function startRuntimeBuild(request: BuildRequest): ResultAsync<BuildRunDetail, ApiError> {
	return apiRequest<BuildRunDetail>('/v1/compute/builds', {
		method: 'POST',
		body: JSON.stringify(request)
	});
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
	return createStream(endpoint, {
		parse: parseBuildMessage,
		isSnapshot: isSnapshotMessage,
		extractSnapshot: (msg) => msg,
		extractEvent: (msg) => {
			const event = protocolBuildEventToBuildEvent(msg);
			if (event === null) {
				callbacks.onError('Invalid build stream event');
				return null;
			}
			return event;
		},
		callbacks: {
			onSnapshot: callbacks.onSnapshot,
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

function parseBuildListMessage(data: string): BuildListStreamMessage | null {
	try {
		const parsed: unknown = JSON.parse(data);
		if (!isRecord(parsed)) return null;
		if (parsed.type === 'snapshot' && Array.isArray(parsed.builds)) {
			return parsed as unknown as BuildListSnapshotMessage;
		}
		if (isErrorMessage(parsed)) return parsed;
		return null;
	} catch {
		return null;
	}
}

export interface BuildListStreamCallbacks {
	onSnapshot: (builds: BuildRunSummary[]) => void;
	onError: (error: string) => void;
	onClose: () => void;
}

/**
 * Subscribe to namespace build changes. The server sends active build
 * snapshots; the history store follows each notification with the current
 * filtered REST query so terminal and historical rows are rendered too.
 */
export function connectBuildListStream(callbacks: BuildListStreamCallbacks): StreamHandle {
	return createStream('/v1/compute/ws/builds', {
		parse: parseBuildListMessage,
		isSnapshot: (msg): msg is BuildListSnapshotMessage => msg.type === 'snapshot',
		extractSnapshot: (msg) => msg.builds,
		callbacks
	});
}
