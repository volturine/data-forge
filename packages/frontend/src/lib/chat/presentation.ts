import type { MCPTool } from '$lib/api/mcp';
import type { TimelineEntry } from '$lib/stores/chat.svelte';
import { formatEpoch, isSameLocalDay, isYesterday, nowEpochMs } from '$lib/utils/temporal';

export function timelineEntriesAreGrouped(timeline: TimelineEntry[], index: number): boolean {
	if (index === 0) return false;
	const current = timeline[index];
	const previous = timeline[index - 1];
	return (
		current.kind === 'message' &&
		previous.kind === 'message' &&
		current.item.role === previous.item.role &&
		current.item.role !== 'tool'
	);
}

export function timelineDateSeparator(timeline: TimelineEntry[], index: number): string | null {
	const entry = timeline[index];
	const timestamp = entry.kind === 'message' ? entry.item.ts : 0;
	if (!timestamp) return null;
	for (let cursor = index - 1; cursor >= 0; cursor--) {
		const previous = timeline[cursor];
		const previousTimestamp = previous.kind === 'message' ? previous.item.ts : 0;
		if (previousTimestamp) {
			return isSameLocalDay(timestamp, previousTimestamp) ? null : formatDateLabel(timestamp);
		}
	}
	return index === 0 ? formatDateLabel(timestamp) : null;
}

function formatDateLabel(timestamp: number): string {
	const now = nowEpochMs();
	if (isSameLocalDay(timestamp, now)) return 'Today';
	if (isYesterday(timestamp, now)) return 'Yesterday';
	return formatEpoch(timestamp, { weekday: 'short', month: 'short', day: 'numeric' });
}

export function toolDisplayName(toolId: string, method: string): string {
	const verb =
		{ GET: 'Get', POST: 'Create', PUT: 'Update', PATCH: 'Update', DELETE: 'Delete' }[method] ??
		method;
	const name = toolId
		.replace(/^(get|post|put|patch|delete)_/i, '')
		.replace(/_/g, ' ')
		.replace(/\b\w/g, (character) => character.toUpperCase());
	return `${verb} ${name}`;
}

export function resultSummary(result: unknown): string {
	if (!result || typeof result !== 'object') return '';
	const response = result as { ok?: boolean; status?: number };
	if (response.ok === false) return `Error ${response.status ?? ''}`;
	if (response.ok === true) return `OK ${response.status ?? 200}`;
	return '';
}

export function outputHint(tool: MCPTool | undefined): string | null {
	return tool?.output_schema?.hint ?? null;
}

export function formatDuration(milliseconds: number): string {
	return milliseconds < 1000 ? `${milliseconds}ms` : `${(milliseconds / 1000).toFixed(1)}s`;
}

export function methodColor(method: string): string {
	if (method === 'GET') return 'fg.success';
	if (method === 'DELETE') return 'fg.error';
	if (method === 'POST') return 'fg.primary';
	return 'fg.warning';
}

export function formatTokens(count: number): string {
	if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`;
	if (count >= 1_000) return `${(count / 1_000).toFixed(1)}k`;
	return String(count);
}
