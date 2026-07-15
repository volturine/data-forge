import { Marked } from 'marked';
import DOMPurify from 'dompurify';
import { formatEpoch, isSameLocalDay, isYesterday, nowEpochMs } from '$lib/utils/temporal';

const marked = new Marked({
	breaks: true,
	gfm: true
});

export function renderMarkdown(text: string): string {
	const raw = marked.parse(text);
	if (typeof raw !== 'string') return text;
	return DOMPurify.sanitize(raw);
}

export function timeAgo(ts: number): string {
	const now = nowEpochMs();
	const time = formatEpoch(ts, { hour: '2-digit', minute: '2-digit' });
	if (isSameLocalDay(ts, now)) return time;
	if (isYesterday(ts, now)) return `Yesterday ${time}`;
	return `${formatEpoch(ts, { month: 'short', day: 'numeric' })} ${time}`;
}
