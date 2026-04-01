import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
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

beforeEach(() => {
	statusQueryState = { data: undefined, error: null, isLoading: false, isFetching: false };
	subscribersQueryState = { data: undefined, error: null, isLoading: false, isFetching: false };
	mockGetSettings.mockReset();
	mockUpdateSettings.mockReset();
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

	describe('SMTP section', () => {
		test('shows SMTP section header', () => {
			renderPopup();
			expect(screen.getByText('SMTP')).toBeInTheDocument();
		});

		test('shows Host input', () => {
			renderPopup();
			expect(screen.getByPlaceholderText('smtp.example.com')).toBeInTheDocument();
		});

		test('shows Port input', () => {
			renderPopup();
			expect(screen.getByDisplayValue('587')).toBeInTheDocument();
		});

		test('shows Test button', () => {
			renderPopup();
			expect(screen.getByText('Test')).toBeInTheDocument();
		});

		test('test button is disabled without recipient', () => {
			renderPopup();
			const btn = screen.getByText('Test').closest('button');
			expect(btn).toBeDisabled();
		});
	});

	describe('Telegram section', () => {
		test('shows Telegram section header', () => {
			renderPopup();
			expect(screen.getByText('Telegram')).toBeInTheDocument();
		});

		test('shows Bot token input', () => {
			renderPopup();
			const el = document.getElementById('telegram-bot-token');
			expect(el).toBeInTheDocument();
			expect(el).toHaveAttribute('type', 'password');
		});

		test('shows Enable Bot toggle', () => {
			renderPopup();
			expect(screen.getByLabelText('Toggle Telegram bot')).toBeInTheDocument();
		});

		test('toggle has switch role', () => {
			renderPopup();
			const toggle = screen.getByLabelText('Toggle Telegram bot');
			expect(toggle).toHaveAttribute('role', 'switch');
		});

		test('toggle shows unchecked by default', () => {
			renderPopup();
			const toggle = screen.getByLabelText('Toggle Telegram bot');
			expect(toggle).toHaveAttribute('aria-checked', 'false');
		});

		test('shows subscriber prompt when no subscribers', () => {
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
			renderPopup();
			expect(screen.getByText(/Subscribers appear here after users send/)).toBeInTheDocument();
		});

		test('shows bot status when available', () => {
			statusQueryState = {
				data: { running: true, token_configured: true, subscriber_count: 3 },
				error: null,
				isLoading: false,
				isFetching: false
			};
			renderPopup();
			expect(screen.getByText('Bot running')).toBeInTheDocument();
			expect(screen.getByText('3 subscribers')).toBeInTheDocument();
		});

		test('shows bot stopped status', () => {
			statusQueryState = {
				data: { running: false, token_configured: true, subscriber_count: 1 },
				error: null,
				isLoading: false,
				isFetching: false
			};
			renderPopup();
			expect(screen.getByText('Bot stopped')).toBeInTheDocument();
			expect(screen.getByText('1 subscriber')).toBeInTheDocument();
		});
	});

	describe('Debug section', () => {
		test('shows Debug section header', () => {
			renderPopup();
			expect(screen.getByText('Debug')).toBeInTheDocument();
		});

		test('shows IndexedDB Inspector toggle', () => {
			renderPopup();
			expect(screen.getByLabelText('Toggle IndexedDB inspector')).toBeInTheDocument();
		});

		test('IDB toggle has switch role', () => {
			renderPopup();
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
});
