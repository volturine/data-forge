import type { BuildRequest } from './compute';
import { apiRequest } from './client';
import { createStream, type StreamHandle } from './websocket';
import type { BuildEvent, BuildDetailSnapshot } from '$lib/types/build-stream';
import type { ActiveBuildDetail } from '$lib/types/build-stream';
import type { ResultAsync } from 'neverthrow';
import type { ApiError } from './client';

export type BuildStreamMessage =
	| { type: 'snapshot'; build: BuildDetailSnapshot['build'] }
	| BuildEvent;

export interface BuildStreamCallbacks {
	onSnapshot: (build: BuildDetailSnapshot['build']) => void;
	onEvent: (event: BuildEvent) => void;
	onError: (error: string) => void;
	onClose: () => void;
}

function parseBuildMessage(data: string): BuildStreamMessage | null {
	try {
		return JSON.parse(data) as BuildStreamMessage;
	} catch {
		return null;
	}
}

export function startActiveBuild(request: BuildRequest): ResultAsync<ActiveBuildDetail, ApiError> {
	return apiRequest<ActiveBuildDetail>('/v1/compute/builds/active', {
		method: 'POST',
		body: JSON.stringify(request)
	});
}

function isBuildDetailSnapshot(msg: BuildStreamMessage): msg is BuildDetailSnapshot {
	return msg.type === 'snapshot';
}

function toBuildDetailEvent(msg: BuildStreamMessage): BuildEvent {
	if (isBuildDetailSnapshot(msg)) {
		throw new Error('Expected build event');
	}
	return msg;
}

function getBuildDetailSnapshot(msg: BuildStreamMessage): BuildDetailSnapshot['build'] {
	if (!isBuildDetailSnapshot(msg)) {
		throw new Error('Expected build snapshot');
	}
	return msg.build;
}

export function connectBuildDetailStream(
	buildId: string,
	callbacks: BuildStreamCallbacks
): StreamHandle {
	return createStream<BuildDetailSnapshot['build'], BuildEvent, BuildStreamMessage>(
		`/v1/compute/ws/builds/${buildId}`,
		{
			parse: parseBuildMessage,
			isSnapshot: isBuildDetailSnapshot,
			extractSnapshot: getBuildDetailSnapshot,
			extractEvent: toBuildDetailEvent,
			callbacks
		}
	);
}

export function getActiveBuild(buildId: string): ResultAsync<ActiveBuildDetail, ApiError> {
	return apiRequest<ActiveBuildDetail>(`/v1/compute/builds/active/${buildId}`);
}

export function getActiveBuildByEngineRun(
	engineRunId: string
): ResultAsync<ActiveBuildDetail, ApiError> {
	return apiRequest<ActiveBuildDetail>(`/v1/compute/builds/active/by-engine-run/${engineRunId}`);
}
