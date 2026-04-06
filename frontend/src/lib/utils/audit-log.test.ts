import { describe, test, expect, vi, beforeAll, beforeEach, afterAll } from 'vitest';

vi.mock('$app/environment', () => ({
	browser: true,
	building: false,
	dev: true,
	version: 'test'
}));

vi.mock('$lib/utils/indexeddb', () => ({
	idbGet: vi.fn().mockResolvedValue(null),
	idbSet: vi.fn().mockResolvedValue(undefined)
}));

vi.mock('$lib/stores/clientIdentity.svelte', () => ({
	getClientIdentity: () => ({ clientId: 'test-client', clientSignature: 'test-sig' })
}));

vi.mock('$lib/stores/config.svelte', () => ({
	configStore: {
		config: {
			log_client_dedupe_window_ms: 0,
			log_queue_max_size: 100,
			log_client_batch_size: 50,
			log_client_flush_interval_ms: 5000,
			log_client_flush_cooldown_ms: 10000
		}
	}
}));

const fetchSpy = vi.fn().mockResolvedValue({ ok: true });
vi.stubGlobal('fetch', fetchSpy);

const { flush, setAuditPage, track, installAuditListeners } = await import('./audit-log');

describe('audit-log', () => {
	beforeAll(() => {
		vi.useFakeTimers();
	});

	afterAll(() => {
		vi.useRealTimers();
	});

	beforeEach(() => {
		vi.advanceTimersByTime(10000);
		flush();
		fetchSpy.mockClear();
	});

	describe('flush', () => {
		test('sends POST to audit endpoint with correct headers', () => {
			track({ event: 'flush_check' });
			flush();
			expect(fetchSpy).toHaveBeenCalledWith(
				'/api/v1/logs/client',
				expect.objectContaining({
					method: 'POST',
					headers: expect.objectContaining({
						'Content-Type': 'application/json',
						'X-Client-Id': 'test-client'
					}),
					keepalive: true
				})
			);
		});

		test('does nothing when buffer is empty', () => {
			flush();
			flush();
			expect(fetchSpy).not.toHaveBeenCalled();
		});

		test('includes X-Client-Session header', () => {
			track({ event: 'session_check' });
			flush();
			const headers = fetchSpy.mock.calls[0][1].headers;
			expect(headers['X-Client-Session']).toBeTruthy();
		});

		test('sends JSON body with logs array', () => {
			track({ event: 'body_check' });
			flush();
			const body = JSON.parse(fetchSpy.mock.calls[0][1].body);
			expect(body.logs).toBeDefined();
			expect(Array.isArray(body.logs)).toBe(true);
		});
	});

	describe('track', () => {
		test('buffers events and flushes on timer', () => {
			track({ event: 'timer_test' });
			expect(fetchSpy).not.toHaveBeenCalled();
			vi.advanceTimersByTime(5001);
			expect(fetchSpy).toHaveBeenCalledOnce();
		});

		test('includes event data in flushed payload', () => {
			track({ event: 'payload_test', action: 'hover', target: 'icon' });
			flush();
			const body = JSON.parse(fetchSpy.mock.calls[0][1].body);
			const match = body.logs.find((l: Record<string, unknown>) => l.event === 'payload_test');
			expect(match).toBeDefined();
			expect(match.action).toBe('hover');
			expect(match.target).toBe('icon');
		});

		test('attaches session_id to tracked events', () => {
			track({ event: 'session_attach' });
			flush();
			const body = JSON.parse(fetchSpy.mock.calls[0][1].body);
			const match = body.logs.find((l: Record<string, unknown>) => l.event === 'session_attach');
			expect(match.session_id).toBeTruthy();
			expect(match.session_id).toMatch(/^s-/);
		});

		test('uses page from setAuditPage when not specified', () => {
			setAuditPage('/settings');
			flush();
			fetchSpy.mockClear();
			track({ event: 'page_inherit' });
			flush();
			const body = JSON.parse(fetchSpy.mock.calls[0][1].body);
			const match = body.logs.find((l: Record<string, unknown>) => l.event === 'page_inherit');
			expect(match.page).toBe('/settings');
		});

		test('allows overriding page per event', () => {
			setAuditPage('/default');
			flush();
			fetchSpy.mockClear();
			track({ event: 'page_override', page: '/custom' });
			flush();
			const body = JSON.parse(fetchSpy.mock.calls[0][1].body);
			const match = body.logs.find((l: Record<string, unknown>) => l.event === 'page_override');
			expect(match.page).toBe('/custom');
		});
	});

	describe('setAuditPage', () => {
		test('emits page_view event with path', () => {
			setAuditPage('/home');
			flush();
			const body = JSON.parse(fetchSpy.mock.calls[0][1].body);
			const pageView = body.logs.find(
				(l: Record<string, unknown>) => l.event === 'page_view' && l.page === '/home'
			);
			expect(pageView).toBeDefined();
			expect(pageView.page).toBe('/home');
		});
	});

	describe('field redaction', () => {
		beforeEach(() => {
			installAuditListeners();
		});

		test('redacts password fields on form submit', () => {
			const form = document.createElement('form');
			const text = document.createElement('input');
			text.type = 'text';
			text.name = 'username';
			text.value = 'alice';
			form.appendChild(text);
			const pw = document.createElement('input');
			pw.type = 'password';
			pw.name = 'smtp_password';
			pw.value = 'super-secret-123';
			form.appendChild(pw);
			document.body.appendChild(form);

			form.dispatchEvent(new Event('submit', { bubbles: true }));
			flush();

			const body = JSON.parse(fetchSpy.mock.calls[0][1].body);
			const submit = body.logs.find((l: Record<string, unknown>) => l.event === 'submit');
			expect(submit).toBeDefined();
			const fields = submit.fields as Array<{
				name: string;
				value: string | null;
				redacted?: boolean;
			}>;
			const pwField = fields.find((f) => f.name === 'smtp_password');
			expect(pwField).toBeDefined();
			expect(pwField!.value).toBeNull();
			expect(pwField!.redacted).toBe(true);
			const textField = fields.find((f) => f.name === 'username');
			expect(textField).toBeDefined();
			expect(textField!.value).toBe('alice');
			expect(textField!.redacted).toBeUndefined();

			document.body.removeChild(form);
		});

		test('redacts fields with sensitive name patterns', () => {
			const form = document.createElement('form');
			const key = document.createElement('input');
			key.type = 'text';
			key.name = 'api_key';
			key.value = 'sk-1234';
			form.appendChild(key);
			const token = document.createElement('input');
			token.type = 'text';
			token.name = 'bot_token';
			token.value = 'tok-5678';
			form.appendChild(token);
			document.body.appendChild(form);

			form.dispatchEvent(new Event('submit', { bubbles: true }));
			flush();

			const body = JSON.parse(fetchSpy.mock.calls[0][1].body);
			const submit = body.logs.find((l: Record<string, unknown>) => l.event === 'submit');
			const fields = submit.fields as Array<{
				name: string;
				value: string | null;
				redacted?: boolean;
			}>;
			for (const f of fields) {
				expect(f.value).toBeNull();
				expect(f.redacted).toBe(true);
			}

			document.body.removeChild(form);
		});

		test('redacts password type inputs on change', () => {
			const pw = document.createElement('input');
			pw.type = 'password';
			pw.name = 'secret_field';
			pw.value = 'changed-password';
			document.body.appendChild(pw);

			pw.dispatchEvent(new Event('change', { bubbles: true }));
			flush();

			const body = JSON.parse(fetchSpy.mock.calls[0][1].body);
			const change = body.logs.find((l: Record<string, unknown>) => l.event === 'change');
			expect(change).toBeDefined();
			const fields = change.fields as Array<{
				name: string;
				value: string | null;
				redacted?: boolean;
			}>;
			expect(fields[0].value).toBeNull();
			expect(fields[0].redacted).toBe(true);

			document.body.removeChild(pw);
		});
	});
});
