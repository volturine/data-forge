import { browser } from '$app/environment';
import { ResultAsync, errAsync, okAsync } from 'neverthrow';
import { getClientIdentity } from '$lib/stores/clientIdentity.svelte';
import { configStore } from '$lib/stores/config.svelte';
import { idbGet, idbSet } from '$lib/utils/indexeddb';

export type AuditField = {
	name: string;
	value?: string | null;
	redacted?: boolean;
};

export type AuditLogItem = {
	event: string;
	action?: string;
	page?: string;
	target?: string;
	form_id?: string;
	fields?: AuditField[];
	client_id?: string;
	session_id?: string;
	meta?: Record<string, unknown> | null;
};

const endpoint = '/api/v1/logs/client';
const buffer: AuditLogItem[] = [];
const dedupe = new Map<string, number>();
const flushFailures = new Map<string, number>();

const state = {
	timer: null as number | null,
	session: '',
	page: '',
	installed: false
};

if (browser) {
	void idbGet<string>('audit_session').then((stored) => {
		if (!stored) return;
		if (state.session) return;
		state.session = stored;
	});
}

function ensureSessionId(): string {
	if (!browser) return '';
	if (state.session) return state.session;
	state.session = `s-${Math.random().toString(16).slice(2)}-${Date.now().toString(16)}`;
	void idbSet('audit_session', state.session);
	return state.session;
}

function shouldSkipTarget(el: Element | null): boolean {
	return !el || !!el.closest('[data-audit="off"]');
}

function getTargetLabel(el: Element | null): string | undefined {
	if (!el) return undefined;
	const audit = el.getAttribute('data-audit-label');
	if (audit) return audit;
	const id = el.getAttribute('id');
	const name = el.getAttribute('name');
	const text = el.textContent?.trim();
	if (id) return `#${id}`;
	if (name) return name;
	if (text && text.length <= 80) return text;
	return el.tagName.toLowerCase();
}

function extractFields(form: HTMLFormElement): AuditField[] {
	const fields: AuditField[] = [];
	const elements = Array.from(form.elements);
	for (const element of elements) {
		if (
			!(
				element instanceof HTMLInputElement ||
				element instanceof HTMLSelectElement ||
				element instanceof HTMLTextAreaElement
			)
		) {
			continue;
		}
		if (element.closest('[data-audit="off"]')) continue;
		const name =
			element.name ||
			element.id ||
			element.getAttribute('data-audit-label') ||
			element.tagName.toLowerCase();
		fields.push({ name, value: element.value ?? '' });
	}
	return fields;
}

function scheduleFlush(flushIntervalMs: number) {
	if (state.timer) return;
	state.timer = window.setTimeout(() => {
		state.timer = null;
		flush();
	}, flushIntervalMs);
}

function pushLog(item: AuditLogItem) {
	if (!browser) return;
	const payload = {
		...item,
		session_id: item.session_id ?? ensureSessionId()
	};
	const config = configStore.config;
	if (!config) return;
	buffer.push(payload);
	const now = Date.now();
	const key = `${payload.event}:${payload.action ?? ''}:${payload.target ?? ''}`;
	const last = dedupe.get(key);
	const dedupeWindowMs = config.log_client_dedupe_window_ms;
	if (last && now - last < dedupeWindowMs) return;
	dedupe.set(key, now);
	const maxBuffer = config.log_queue_max_size;
	if (buffer.length > maxBuffer) {
		buffer.splice(0, buffer.length - maxBuffer);
		scheduleFlush(config.log_client_flush_interval_ms);
		return;
	}
	if (buffer.length >= config.log_client_batch_size) {
		flush();
		return;
	}
	scheduleFlush(config.log_client_flush_interval_ms);
}

function recordFlushFailure(error: string, payload: AuditLogItem[]) {
	const config = configStore.config;
	if (!config) return;
	const last = flushFailures.get(error);
	const now = Date.now();
	const flushCooldownMs = config.log_client_flush_cooldown_ms;
	if (last && now - last < flushCooldownMs) return;
	flushFailures.set(error, now);
	buffer.unshift(
		{
			event: 'audit_error',
			action: 'flush',
			target: 'client',
			meta: { error, dropped: payload.length }
		},
		...payload
	);
	scheduleFlush(config.log_client_flush_interval_ms);
}

export function flush() {
	if (!browser || buffer.length === 0) return;
	const clientId = getClientIdentity().clientId;
	const payload = buffer.splice(0, buffer.length);

	ResultAsync.fromPromise(
		fetch(endpoint, {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json',
				'X-Client-Id': clientId,
				'X-Client-Session': ensureSessionId()
			},
			body: JSON.stringify({ logs: payload }),
			keepalive: true
		}),
		(error) => (error instanceof Error ? error.message : 'Audit log network error')
	)
		.andThen((response) => {
			if (response.ok) return okAsync(true);
			const fallback = response.statusText || `Audit log request failed (${response.status})`;
			return ResultAsync.fromPromise(response.text(), () => fallback).andThen((body) =>
				errAsync(body || fallback)
			);
		})
		.match(
			() => {},
			(error) => {
				recordFlushFailure(String(error), payload);
			}
		);
}

export function setAuditPage(path: string) {
	state.page = path;
	pushLog({ event: 'page_view', page: path, session_id: ensureSessionId() });
}

export function track(event: AuditLogItem) {
	pushLog({
		...event,
		page: event.page ?? state.page
	});
}

export function installAuditListeners() {
	if (!browser) return;
	if (state.installed) return;
	state.installed = true;
	ensureSessionId();

	const onClick = (event: MouseEvent) => {
		const target = event.target instanceof Element ? event.target : null;
		if (shouldSkipTarget(target)) return;
		const label = getTargetLabel(target);
		pushLog({
			event: 'click',
			action: 'click',
			target: label,
			page: state.page,
			session_id: state.session
		});
	};

	const onSubmit = (event: Event) => {
		const form = event.target instanceof HTMLFormElement ? event.target : null;
		if (!form || shouldSkipTarget(form)) return;
		const label = getTargetLabel(form);
		const fields = extractFields(form);
		pushLog({
			event: 'submit',
			action: 'submit',
			form_id: label,
			fields,
			page: state.page,
			session_id: state.session
		});
	};

	const onChange = (event: Event) => {
		const target = event.target;
		if (!(target instanceof HTMLSelectElement || target instanceof HTMLInputElement)) return;
		if (shouldSkipTarget(target)) return;
		if (target instanceof HTMLInputElement && target.type === 'text') return;
		const name = target.name || target.id || target.tagName.toLowerCase();
		pushLog({
			event: 'change',
			action: target.type || target.tagName.toLowerCase(),
			target: name,
			fields: [{ name, value: target.value ?? '' }],
			page: state.page,
			session_id: state.session
		});
	};

	const onVisibility = () => {
		if (document.visibilityState === 'hidden') flush();
	};

	window.addEventListener('click', onClick, { capture: true });
	window.addEventListener('submit', onSubmit, { capture: true });
	window.addEventListener('change', onChange, { capture: true });
	window.addEventListener('visibilitychange', onVisibility);
	window.addEventListener('beforeunload', flush);
}
