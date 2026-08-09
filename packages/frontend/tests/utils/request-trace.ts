import type { Page, Request, Response } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';

export interface RequestTraceEntry {
	workerIndex: number;
	title: string;
	method: string;
	url: string;
	startEpochMs: number;
	endEpochMs: number | null;
	startMs: number;
	endMs: number | null;
	durationMs: number | null;
	status: number | null;
	targetStepId: string | null;
}

export interface RequestTrace {
	entries: RequestTraceEntry[];
	attach(): void;
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

function safeFilePart(value: string): string {
	return value
		.replace(/[^a-zA-Z0-9_-]+/g, '_')
		.replace(/^_+|_+$/g, '')
		.slice(0, 120);
}

/**
 * Records page API requests with per-request timing. This is enabled only when
 * PLAYWRIGHT_REQUEST_TRACE_DIR is set, so ordinary E2E runs have no tracing
 * listeners or filesystem writes.
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

	const onRequest = (request: Request): void => {
		if (!request.url().includes('/api/')) return;
		const startEpochMs = Date.now();
		const entry: RequestTraceEntry = {
			workerIndex,
			title,
			method: request.method(),
			url: request.url(),
			startEpochMs,
			endEpochMs: null,
			startMs: startEpochMs - startedAt,
			endMs: null,
			durationMs: null,
			status: null,
			targetStepId: extractTargetStep(request.url(), request.postData())
		};
		entries.push(entry);
		byRequest.set(request, entry);
	};

	const onResponse = (response: Response): void => {
		const entry = byRequest.get(response.request());
		if (entry) entry.status = response.status();
	};

	const finish = (request: Request): void => {
		const entry = byRequest.get(request);
		if (!entry) return;
		entry.endEpochMs = Date.now();
		entry.endMs = entry.endEpochMs - startedAt;
		entry.durationMs = entry.endMs - entry.startMs;
		byRequest.delete(request);
	};

	page.on('request', onRequest);
	page.on('response', onResponse);
	page.on('requestfinished', finish);
	page.on('requestfailed', finish);

	return {
		entries,
		attach() {
			page.off('request', onRequest);
			page.off('response', onResponse);
			page.off('requestfinished', finish);
			page.off('requestfailed', finish);
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
