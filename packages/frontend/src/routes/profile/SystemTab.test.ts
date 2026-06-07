import { describe, expect, test, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';

type Matchable<T> = {
	match: (onOk: (value: T) => void, onErr?: (error: { message: string }) => void) => Promise<void>;
};

function okMatch<T>(value: T): Matchable<T> {
	return {
		match: async (onOk) => {
			onOk(value);
		}
	};
}

const mockGetSettings = vi.fn();
const mockUpdateSettings = vi.fn();
const mockListInternalPostgresTables = vi.fn();
const mockToggleInternalPostgresTable = vi.fn();

vi.mock('$lib/api/settings', () => ({
	getSettings: (...args: unknown[]) => mockGetSettings(...args),
	updateSettings: (...args: unknown[]) => mockUpdateSettings(...args)
}));

vi.mock('$lib/api/datasource', () => ({
	listInternalPostgresTables: (...args: unknown[]) => mockListInternalPostgresTables(...args),
	toggleInternalPostgresTable: (...args: unknown[]) => mockToggleInternalPostgresTable(...args)
}));

vi.mock('$lib/stores/namespace.svelte', () => ({
	useNamespace: () => ({
		ready: true,
		value: 'default'
	})
}));

vi.mock('@lucide/svelte', () => {
	const Icon = () => '';
	return {
		Loader2: Icon,
		CheckCircle: Icon,
		XCircle: Icon,
		Save: Icon,
		Database: Icon,
		ChevronDown: Icon
	};
});

const { default: SystemTab } = await import('./SystemTab.svelte');

describe('SystemTab', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockGetSettings.mockReturnValue(
			okMatch({
				public_idb_debug: false
			})
		);
		mockUpdateSettings.mockReturnValue(okMatch({}));
		mockListInternalPostgresTables.mockReturnValue(
			okMatch([
				{
					schema_name: 'default',
					table_name: 'analyses',
					is_onboarded: false
				}
			])
		);
	});

	test('onboard switch stays on persisted state until toggle request completes', async () => {
		const toggleControl: {
			resolve: (
				result: Matchable<{ schema_name: string; table_name: string; is_onboarded: boolean }>
			) => void;
		} = {
			resolve: () => {
				throw new Error('toggle promise resolver was not set');
			}
		};
		mockToggleInternalPostgresTable.mockReturnValue(
			new Promise<Matchable<{ schema_name: string; table_name: string; is_onboarded: boolean }>>(
				(resolve) => {
					toggleControl.resolve = resolve;
				}
			)
		);

		render(SystemTab);

		const groupToggle = await screen.findByRole('button', { name: /Namespace tables: default/i });
		await fireEvent.click(groupToggle);

		const onboardSwitch = await screen.findByLabelText('Onboard table default.analyses');
		expect(onboardSwitch).toHaveAttribute('aria-checked', 'false');
		expect(onboardSwitch).toBeEnabled();

		await fireEvent.click(onboardSwitch);

		expect(mockToggleInternalPostgresTable).toHaveBeenCalledWith('default', 'analyses', true);
		expect(onboardSwitch).toHaveAttribute('aria-checked', 'false');
		expect(onboardSwitch).toBeDisabled();
		expect(screen.getByText('Toggling…')).toBeVisible();

		toggleControl.resolve(
			okMatch({
				schema_name: 'default',
				table_name: 'analyses',
				is_onboarded: true
			})
		);

		await waitFor(() => {
			expect(onboardSwitch).toHaveAttribute('aria-checked', 'true');
			expect(onboardSwitch).toBeEnabled();
		});
	});
});
