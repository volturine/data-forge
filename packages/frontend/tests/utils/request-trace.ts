import type { Page, Request, Response } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';

export interface RequestTraceEntry {
	workerIndex: number;
	title: string;
	method: string;
	url: string;
	resourceId: string | null;
	startEpochMs: number;
	endEpochMs: number | null;
	startMs: number;
	endMs: number | null;
	durationMs: number | null;
	serverDurationMs: number | null;
	status: number | null;
	requestId: string | null;
	responseFields: string[] | null;
	responseBuildId: string | null;
	failureText: string | null;
	targetStepId: string | null;
}

export interface RequestTrace {
	entries: RequestTraceEntry[];
	attach(): Promise<void>;
}

function extractTargetStep(url: string, postData: string | null): string | null {
	if (!/\/compute\/(preview|schema)\/?(?:\?|$)/.test(url) || !postData) return null;
	try {
		const body: unknown = JSON.parse(postData);
		if (typeof body !== 'object' || body === null || !('target_step_id' in body)) return null;
		return typeof body.target_step_id === 'string' ? body.target_step_id : null;
	} catch {
		return null;
	}
}

function extractResourceId(url: string, postData: string | null): string | null {
	if (!/\/compute\/(preview|schema)\/?(?:\?|$)/.test(url) || !postData) return null;
	try {
		const body: unknown = JSON.parse(postData);
		if (typeof body !== 'object' || body === null) return null;
		const record = body as Record<string, unknown>;
		const pipeline = record.analysis_pipeline;
		const pipelineRecord =
			typeof pipeline === 'object' && pipeline !== null
				? (pipeline as Record<string, unknown>)
				: null;
		const resourceId =
			record.resource_id ??
			record.analysis_id ??
			record.datasource_id ??
			pipelineRecord?.analysis_id ??
			pipelineRecord?.datasource_id;
		return typeof resourceId === 'string' ? resourceId : null;
	} catch {
		return null;
	}
}

function safeFilePart(value: string): string {
	return value
		.replace(/[^a-zA-Z0-9_-]+/g, '_')
		.replace(/^_+|_+$/g, '')
		.slice(0, 120);
}

function safeRequestUrl(raw: string): string {
	try {
		const url = new URL(raw);
		return `${url.origin}${url.pathname}`;
	} catch {
		return raw.split('?', 1)[0];
	}
}

/**
 * Records page API request timing without query values. The E2E runner points
 * this at a run-scoped ignored artifact directory; unit tests leave it unset.
 */
export function createRequestTrace(
	page: Page,
	workerIndex: number,
	title: string,
	testId: string
): RequestTrace | null {
	const dir = process.env.PLAYWRIGHT_REQUEST_TRACE_DIR;
	if (!dir) return null;

	const startedAt = Date.now();
	const entries: RequestTraceEntry[] = [];
	const byRequest = new Map<Request, RequestTraceEntry>();
	const responseReads: Promise<void>[] = [];

	const onRequest = (request: Request): void => {
		if (!request.url().includes('/api/')) return;
		const startEpochMs = Date.now();
		const entry: RequestTraceEntry = {
			workerIndex,
			title,
			method: request.method(),
			url: safeRequestUrl(request.url()),
			resourceId: extractResourceId(request.url(), request.postData()),
			startEpochMs,
			endEpochMs: null,
			startMs: startEpochMs - startedAt,
			endMs: null,
			durationMs: null,
			serverDurationMs: null,
			status: null,
			requestId: null,
			responseFields: null,
			responseBuildId: null,
			failureText: null,
			targetStepId: extractTargetStep(request.url(), request.postData())
		};
		entries.push(entry);
		byRequest.set(request, entry);
	};

	const onResponse = (response: Response): void => {
		const entry = byRequest.get(response.request());
		if (!entry) return;
		entry.status = response.status();
		const headers = response.headers();
		entry.requestId = headers['x-request-id'] ?? null;
		const serverDuration = headers['server-timing']?.match(
			/(?:^|,)\s*app;dur=(\d+(?:\.\d+)?)/i
		)?.[1];
		entry.serverDurationMs = serverDuration === undefined ? null : Number(serverDuration);
		if (
			response.request().method() === 'POST' &&
			new URL(response.url()).pathname.endsWith('/api/v1/compute/builds')
		) {
			responseReads.push(
				response
					.json()
					.then((body: unknown) => {
						if (typeof body !== 'object' || body === null || Array.isArray(body)) return;
						entry.responseFields = Object.keys(body).sort();
						const buildId = (body as Record<string, unknown>).build_id;
						entry.responseBuildId = typeof buildId === 'string' ? buildId : null;
					})
					.catch(() => undefined)
			);
		}
	};

	const finish = (request: Request): void => {
		const entry = byRequest.get(request);
		if (!entry) return;
		entry.endEpochMs = Date.now();
		entry.endMs = entry.endEpochMs - startedAt;
		entry.durationMs = entry.endMs - entry.startMs;
		byRequest.delete(request);
	};
	const onRequestFailed = (request: Request): void => {
		const entry = byRequest.get(request);
		if (entry) entry.failureText = request.failure()?.errorText ?? null;
		finish(request);
	};

	page.on('request', onRequest);
	page.on('response', onResponse);
	page.on('requestfinished', finish);
	page.on('requestfailed', onRequestFailed);

	return {
		entries,
		async attach() {
			page.off('request', onRequest);
			page.off('response', onResponse);
			page.off('requestfinished', finish);
			page.off('requestfailed', onRequestFailed);
			await Promise.all(responseReads);
			if (entries.length === 0) return;
			const file = path.join(
				dir,
				`worker-${workerIndex}-${safeFilePart(testId)}-${safeFilePart(title)}.jsonl`
			);
			mkdirSync(dir, { recursive: true });
			writeFileSync(file, `${entries.map((entry) => JSON.stringify(entry)).join('\n')}\n`);
		}
	};
}
