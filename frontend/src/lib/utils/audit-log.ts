import { browser } from '$app/environment';
import { getClientIdentity } from '$lib/stores/clientIdentity.svelte';

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
const batch = 20;
const interval = 5000;
const limit = 512;
const cap = 200;
const mask = /(token|secret|key|auth|bearer)/i;
const jwt = /eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+/;
const state = {
	timer: null as number | null,
	session: '',
	page: '',
	installed: false
};

function ensureSessionId(): string {
	if (!browser) return '';
	if (state.session) return state.session;
	const stored = sessionStorage.getItem('audit_session');
	if (stored) {
		state.session = stored;
		return state.session;
	}
	state.session = `s-${Math.random().toString(16).slice(2)}-${Date.now().toString(16)}`;
	sessionStorage.setItem('audit_session', state.session);
	return state.session;
}

function shouldSkipTarget(el: Element | null): boolean {
	if (!el) return true;
	if (el.closest('[data-audit="off"]')) return true;
	return false;
}

function redactValue(
	name: string,
	value: string,
	el?: Element | null
): { value: string; redacted: boolean } {
	if (el && el.closest('[data-audit="redact"]')) return { value: '[redacted]', redacted: true };
	if (el instanceof HTMLInputElement && el.type === 'password')
		return { value: '[redacted]', redacted: true };
	if (mask.test(name)) return { value: '[redacted]', redacted: true };
	if (jwt.test(value)) return { value: '[redacted]', redacted: true };
	if (value.length > limit) return { value: value.slice(0, limit), redacted: true };
	return { value, redacted: false };
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
		const raw = element.value ?? '';
		const { value, redacted } = redactValue(name, raw, element);
		fields.push({ name, value, redacted });
	}
	return fields;
}

function pushLog(item: AuditLogItem) {
	if (!browser) return;
	const payload = {
		...item,
		session_id: item.session_id ?? ensureSessionId()
	};
	const now = Date.now();
	const key = `${payload.event}:${payload.action ?? ''}:${payload.target ?? ''}`;
	const last = dedupe.get(key);
	if (last && now - last < 500) return;
	dedupe.set(key, now);
	buffer.push(payload);
	if (buffer.length > cap) {
		buffer.splice(0, buffer.length - cap);
	}
	if (buffer.length >= batch) {
		flush();
		return;
	}
	if (state.timer) return;
	state.timer = window.setTimeout(() => {
		state.timer = null;
		flush();
	}, interval);
}

export function flush() {
	if (!browser || buffer.length === 0) return;
	const { clientId } = getClientIdentity();
	const payload = buffer.splice(0, buffer.length);
	fetch(endpoint, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			'X-Client-Id': clientId,
			'X-Client-Session': ensureSessionId()
		},
		body: JSON.stringify({ logs: payload }),
		keepalive: true
	}).catch(() => {});
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
		const { value, redacted } = redactValue(name, target.value ?? '', target);
		pushLog({
			event: 'change',
			action: target.type || target.tagName.toLowerCase(),
			target: name,
			fields: [{ name, value, redacted }],
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
