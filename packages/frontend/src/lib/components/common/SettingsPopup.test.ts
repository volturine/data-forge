import { describe, test, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import SettingsPopup from './SettingsPopup.svelte';

const mockGetSettings = vi.fn();
const mockUpdateSettings = vi.fn();
const mockTestSmtp = vi.fn();
const mockGetBotStatus = vi.fn();
const mockGetSubscribers = vi.fn();
const mockDeleteSubscriber = vi.fn();

vi.mock('$lib/api/settings', () => ({
	getSettings: (...args: unknown[]) => mockGetSettings(...args),
	updateSettings: (...args: unknown[]) => mockUpdateSettings(...args),
	testSmtp: (...args: unknown[]) => mockTestSmtp(...args),
	getBotStatus: (...args: unknown[]) => mockGetBotStatus(...args),
	getSubscribers: (...args: unknown[]) => mockGetSubscribers(...args),
	deleteSubscriber: (...args: unknown[]) => mockDeleteSubscriber(...args),
	MASKED_PLACEHOLDER: '••••••••',
	isMasked: (v: string) => v === '••••••••' || /^\*+$/.test(v)
}));

vi.mock('$lib/stores/config.svelte', () => ({
	configStore: {
		fetched: false,
		fetch: vi.fn()
	}
}));

let statusQueryState: Record<string, unknown> = {};
let subscribersQueryState: Record<string, unknown> = {};

vi.mock('@tanstack/svelte-query', () => ({
	createQuery: (optsFn: () => Record<string, unknown>) => {
		const opts = optsFn();
		const key = (opts.queryKey as string[])[0];
		if (key === 'telegram-status') return statusQueryState;
		if (key === 'telegram-subscribers') return subscribersQueryState;
		return { data: undefined, error: null, isLoading: false };
	},
	createMutation: () => ({
		mutate: vi.fn(),
		isPending: false
	}),
	useQueryClient: () => ({
		invalidateQueries: vi.fn()
	})
}));

function makeSettingsResponse() {
	return {
		smtp_host: 'smtp.test.com',
		smtp_port: 587,
		smtp_user: 'user@test.com',
		smtp_password: '••••••••',
		telegram_bot_token: '••••••••',
		telegram_bot_enabled: false,
		openrouter_api_key: '',
		public_idb_debug: false
	};
}

function renderPopup(props: Record<string, unknown> = {}) {
	mockGetSettings.mockReturnValue({
		match: (onOk: (v: unknown) => void) => {
			onOk(makeSettingsResponse());
		}
	});
	return render(SettingsPopup, {
		props: {
			open: true,
			...props
		}
	});
}

async function renderPopupWithExpandedSections(
	sectionNames: readonly string[],
	props: Record<string, unknown> = {}
) {
	const view = renderPopup(props);
	for (const name of sectionNames) {
		const toggle = screen.getByRole('button', { name });
		if (toggle.getAttribute('aria-expanded') === 'false') {
			await fireEvent.click(toggle);
		}
	}
	return view;
}

beforeEach(() => {
	statusQueryState = { data: undefined, error: null, isLoading: false, isFetching: false };
	subscribersQueryState = { data: undefined, error: null, isLoading: false, isFetching: false };
	mockGetSettings.mockReset();
	mockUpdateSettings.mockReset();
	mockTestSmtp.mockReset();
});

describe('SettingsPopup', () => {
	describe('visibility', () => {
		test('renders modal when open', () => {
			renderPopup();
			expect(screen.getByRole('dialog')).toBeInTheDocument();
		});

		test('does not render modal when closed', () => {
			mockGetSettings.mockReturnValue({
				match: () => {}
			});
			render(SettingsPopup, { props: { open: false } });
			expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
		});
	});

	describe('header', () => {
		test('shows Settings title', () => {
			renderPopup();
			expect(screen.getByText('Settings')).toBeInTheDocument();
		});

		test('shows close button', () => {
			renderPopup();
			expect(screen.getByLabelText('Close settings')).toBeInTheDocument();
		});
	});

	describe('collapsible sections', () => {
		test('all category toggles are collapsed by default', () => {
			renderPopup();
			expect(screen.getByRole('button', { name: 'AI Providers' })).toHaveAttribute(
				'aria-expanded',
				'false'
			);
			expect(screen.getByRole('button', { name: 'SMTP' })).toHaveAttribute(
				'aria-expanded',
				'false'
			);
			expect(screen.getByRole('button', { name: 'Telegram' })).toHaveAttribute(
				'aria-expanded',
				'false'
			);
			expect(screen.getByRole('button', { name: 'Debug' })).toHaveAttribute(
				'aria-expanded',
				'false'
			);
		});

		test('SMTP section can collapse and expand', async () => {
			renderPopup();
			const smtpToggle = screen.getByRole('button', { name: 'SMTP' });
			expect(smtpToggle).toHaveAttribute('aria-expanded', 'false');

			await fireEvent.click(smtpToggle);
			expect(smtpToggle).toHaveAttribute('aria-expanded', 'true');

			const smtpHost = screen.getByPlaceholderText('smtp.example.com');
			expect(smtpHost).toBeVisible();

			await fireEvent.click(smtpToggle);
			expect(smtpToggle).toHaveAttribute('aria-expanded', 'false');
			expect(smtpHost).not.toBeVisible();
		});
	});

	describe('SMTP section', () => {
		test('shows SMTP section header', () => {
			renderPopup();
			expect(screen.getByText('SMTP')).toBeInTheDocument();
		});

		test('shows Host input', async () => {
			await renderPopupWithExpandedSections(['SMTP']);
			expect(screen.getByPlaceholderText('smtp.example.com')).toBeInTheDocument();
		});

		test('shows Port input', async () => {
			await renderPopupWithExpandedSections(['SMTP']);
			expect(screen.getByDisplayValue('587')).toBeInTheDocument();
		});

		test('shows Test button', async () => {
			await renderPopupWithExpandedSections(['SMTP']);
			expect(screen.getByRole('button', { name: 'Test SMTP' })).toBeInTheDocument();
		});

		test('test button is disabled without recipient', async () => {
			await renderPopupWithExpandedSections(['SMTP']);
			const btn = screen.getByRole('button', { name: 'Test SMTP' });
			expect(btn).toBeDisabled();
		});
	});

	describe('Telegram section', () => {
		test('shows Telegram section header', () => {
			renderPopup();
			expect(screen.getByText('Telegram')).toBeInTheDocument();
		});

		test('shows Bot token input', async () => {
			await renderPopupWithExpandedSections(['Telegram']);
			const el = document.getElementById('telegram-bot-token');
			expect(el).toBeInTheDocument();
			expect(el).toHaveAttribute('type', 'password');
		});

		test('shows Enable Bot toggle', async () => {
			await renderPopupWithExpandedSections(['Telegram']);
			expect(screen.getByLabelText('Toggle Telegram bot')).toBeInTheDocument();
		});

		test('toggle has switch role', async () => {
			await renderPopupWithExpandedSections(['Telegram']);
			const toggle = screen.getByLabelText('Toggle Telegram bot');
			expect(toggle).toHaveAttribute('role', 'switch');
		});

		test('toggle shows unchecked by default', async () => {
			await renderPopupWithExpandedSections(['Telegram']);
			const toggle = screen.getByLabelText('Toggle Telegram bot');
			expect(toggle).toHaveAttribute('aria-checked', 'false');
		});

		test('shows subscriber prompt when no subscribers', async () => {
			statusQueryState = {
				data: { running: false, token_configured: false, subscriber_count: 0 },
				error: null,
				isLoading: false,
				isFetching: false
			};
			subscribersQueryState = {
				data: [],
				error: null,
				isLoading: false,
				isFetching: false
			};
			await renderPopupWithExpandedSections(['Telegram']);
			expect(screen.getByText(/Subscribers appear here after users send/)).toBeInTheDocument();
		});

		test('shows bot status when available', async () => {
			statusQueryState = {
				data: { running: true, token_configured: true, subscriber_count: 3 },
				error: null,
				isLoading: false,
				isFetching: false
			};
			await renderPopupWithExpandedSections(['Telegram']);
			expect(screen.getByText('Bot running')).toBeInTheDocument();
			expect(screen.getByText('3 subscribers')).toBeInTheDocument();
		});

		test('shows bot stopped status', async () => {
			statusQueryState = {
				data: { running: false, token_configured: true, subscriber_count: 1 },
				error: null,
				isLoading: false,
				isFetching: false
			};
			await renderPopupWithExpandedSections(['Telegram']);
			expect(screen.getByText('Bot stopped')).toBeInTheDocument();
			expect(screen.getByText('1 subscriber')).toBeInTheDocument();
		});
	});

	describe('Debug section', () => {
		test('shows Debug section header', () => {
			renderPopup();
			expect(screen.getByText('Debug')).toBeInTheDocument();
		});

		test('shows IndexedDB Inspector toggle', async () => {
			await renderPopupWithExpandedSections(['Debug']);
			expect(screen.getByLabelText('Toggle IndexedDB inspector')).toBeInTheDocument();
		});

		test('IDB toggle has switch role', async () => {
			await renderPopupWithExpandedSections(['Debug']);
			const toggle = screen.getByLabelText('Toggle IndexedDB inspector');
			expect(toggle).toHaveAttribute('role', 'switch');
			expect(toggle).toHaveAttribute('aria-checked', 'false');
		});
	});

	describe('save button', () => {
		test('shows Save button', () => {
			renderPopup();
			expect(screen.getByText('Save')).toBeInTheDocument();
		});

		test('shows footer help text', () => {
			renderPopup();
			expect(screen.getByText('Settings are stored in the database.')).toBeInTheDocument();
		});
	});

	describe('loading state', () => {
		test('shows loading when settings are being fetched', () => {
			mockGetSettings.mockReturnValue({
				match: () => {}
			});
			render(SettingsPopup, { props: { open: true } });
			expect(screen.getByText('Loading settings...')).toBeInTheDocument();
		});
	});

	describe('close behavior', () => {
		test('close button click hides dialog', async () => {
			renderPopup();
			expect(screen.getByRole('dialog')).toBeInTheDocument();
			await fireEvent.click(screen.getByLabelText('Close settings'));
			await waitFor(() => {
				expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
			});
		});

		test('Escape key hides dialog', async () => {
			renderPopup();
			expect(screen.getByRole('dialog')).toBeInTheDocument();
			await fireEvent.keyDown(window, { key: 'Escape' });
			await waitFor(() => {
				expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
			});
		});
	});

	describe('Telegram toggle interaction', () => {
		test('clicking toggle flips aria-checked', async () => {
			await renderPopupWithExpandedSections(['Telegram']);
			const toggle = screen.getByLabelText('Toggle Telegram bot');
			expect(toggle).toHaveAttribute('aria-checked', 'false');
			await fireEvent.click(toggle);
			expect(toggle).toHaveAttribute('aria-checked', 'true');
		});
	});

	describe('SMTP test feedback', () => {
		test('shows success message on successful test', async () => {
			mockTestSmtp.mockResolvedValue({
				match: (onOk: (v: unknown) => void) => {
					onOk({ success: true, message: 'Test email sent successfully' });
				}
			});
			await renderPopupWithExpandedSections(['SMTP']);
			const recipient = screen.getByTestId('settings-smtp-test-recipient');
			await fireEvent.input(recipient, { target: { value: 'test@example.com' } });
			await fireEvent.click(screen.getByRole('button', { name: 'Test SMTP' }));
			await waitFor(() => {
				expect(screen.getByText('Test email sent successfully')).toBeInTheDocument();
			});
		});

		test('shows error message on failed test', async () => {
			mockTestSmtp.mockResolvedValue({
				match: (onOk: (v: unknown) => void) => {
					onOk({ success: false, message: 'Connection refused' });
				}
			});
			await renderPopupWithExpandedSections(['SMTP']);
			const recipient = screen.getByTestId('settings-smtp-test-recipient');
			await fireEvent.input(recipient, { target: { value: 'test@example.com' } });
			await fireEvent.click(screen.getByRole('button', { name: 'Test SMTP' }));
			await waitFor(() => {
				expect(screen.getByText('Connection refused')).toBeInTheDocument();
			});
		});
	});

	describe('save error feedback', () => {
		test('shows error banner when save returns failure', async () => {
			mockUpdateSettings.mockResolvedValue({
				match: (_onOk: (v: unknown) => void, onErr: (e: unknown) => void) => {
					onErr({ message: 'Database connection failed' });
				}
			});
			renderPopup();
			await fireEvent.click(screen.getByText('Save'));
			await waitFor(() => {
				expect(screen.getByText('Database connection failed')).toBeInTheDocument();
			});
		});
	});

	describe('load failure resilience', () => {
		test('form renders even when settings fetch fails', async () => {
			mockGetSettings.mockReturnValue({
				match: (_onOk: (v: unknown) => void, onErr: () => void) => {
					onErr();
				}
			});
			render(SettingsPopup, { props: { open: true } });
			expect(screen.getByText('Save')).toBeInTheDocument();
			await fireEvent.click(screen.getByRole('button', { name: 'SMTP' }));
			expect(screen.getByPlaceholderText('smtp.example.com')).toBeInTheDocument();
		});
	});
});
