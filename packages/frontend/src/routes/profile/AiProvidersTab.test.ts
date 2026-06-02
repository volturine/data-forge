import { describe, expect, test, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';

type Matchable<T> = {
	match: (onOk: (value: T) => void, onErr?: (error: { message: string }) => void) => Promise<void>;
	isOk: () => boolean;
	value: T;
};

function okMatch<T>(value: T): Matchable<T> {
	return {
		match: async (onOk) => {
			onOk(value);
		},
		isOk: () => true,
		value
	};
}

const mockGetSettings = vi.fn();
const mockUpdateSettings = vi.fn();
const mockTestAIConnection = vi.fn();
const mockListAIModels = vi.fn();

vi.mock('$lib/api/settings', () => ({
	MASKED_PLACEHOLDER: '••••••••',
	isMasked: (value: string) => value === '••••••••' || /^\*+$/.test(value),
	getSettings: (...args: unknown[]) => mockGetSettings(...args),
	updateSettings: (...args: unknown[]) => mockUpdateSettings(...args)
}));

vi.mock('$lib/api/ai', () => ({
	testAIConnection: (...args: unknown[]) => mockTestAIConnection(...args),
	listAIModels: (...args: unknown[]) => mockListAIModels(...args)
}));

vi.mock('@lucide/svelte', () => {
	const Icon = () => '';
	return {
		Loader2: Icon,
		CheckCircle: Icon,
		XCircle: Icon,
		Save: Icon
	};
});

const { default: AiProvidersTab } = await import('./AiProvidersTab.svelte');

describe('AiProvidersTab', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockGetSettings.mockReturnValue(
			okMatch({
				openrouter_api_key: '',
				openrouter_default_model: 'openai/gpt-4o-mini',
				openai_api_key: '',
				openai_endpoint_url: 'https://api.openai.com',
				openai_default_model: 'gpt-4o-mini',
				openai_organization_id: '',
				ollama_endpoint_url: 'http://localhost:11434',
				ollama_default_model: 'llama3.2',
				huggingface_api_token: '',
				huggingface_default_model: 'google/flan-t5-base'
			})
		);
		mockUpdateSettings.mockReturnValue(okMatch({}));
		mockTestAIConnection.mockReturnValue(
			okMatch({
				ok: false,
				detail: '[Errno 61] Connection refused'
			})
		);
		mockListAIModels.mockReturnValue(okMatch([]));
	});

	test('provider test feedback is rendered inside the tested provider card', async () => {
		const { container } = render(AiProvidersTab);

		await screen.findByRole('button', { name: 'Test Ollama' });
		await fireEvent.click(screen.getByRole('button', { name: 'Test Ollama' }));

		const ollamaHeading = screen.getByText('Ollama');
		const ollamaCard = ollamaHeading.closest('div')?.parentElement;
		expect(ollamaCard).not.toBeNull();

		await waitFor(() => {
			expect(
				within(ollamaCard as HTMLElement).getByText('ollama: [Errno 61] Connection refused')
			).toBeVisible();
		});

		// The provider feedback should stay scoped to the card instead of rendering only
		// once at the top of the full page.
		const feedbackMatches = within(container).getAllByText('ollama: [Errno 61] Connection refused');
		expect(feedbackMatches).toHaveLength(1);
	});
});
