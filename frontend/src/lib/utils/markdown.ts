import { Marked } from 'marked';
import DOMPurify from 'dompurify';

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
	const d = new Date(ts);
	const now = new Date();
	const time = d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
	if (d.toDateString() === now.toDateString()) return time;
	const yesterday = new Date(now);
	yesterday.setDate(yesterday.getDate() - 1);
	if (d.toDateString() === yesterday.toDateString()) return `Yesterday ${time}`;
	return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' + time;
}
