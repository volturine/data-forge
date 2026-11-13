import { describe, expect, test, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import type { UserPublic } from '#lib/api/auth.js';

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

vi.mock('#lib/api/settings.js', () => ({
	getSettings: (...args: unknown[]) => mockGetSettings(...args),
	updateSettings: (...args: unknown[]) => mockUpdateSettings(...args)
}));

vi.mock('#lib/api/datasource.js', () => ({
	listInternalPostgresTables: (...args: unknown[]) => mockListInternalPostgresTables(...args),
	toggleInternalPostgresTable: (...args: unknown[]) => mockToggleInternalPostgresTable(...args)
}));

vi.mock('#lib/stores/namespace.svelte.js', () => ({
	useNamespace: () => ({
		ready: true,
		value: 'default'
	})
}));

// The real store keeps `user` reactive, so tests can sign the admin in after mount.
const { authStore } = await import('#lib/stores/auth.svelte.js');

function setUser(isAdmin: boolean | null) {
	authStore.user = isAdmin === null ? null : ({ is_admin: isAdmin } as UserPublic);
}

const mockConfigRefresh = vi.fn().mockResolvedValue(undefined);
vi.mock('#lib/stores/config.svelte.js', () => ({
	configStore: {
		refresh: (...args: unknown[]) => mockConfigRefresh(...args)
	}
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
		setUser(true);
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

	test('non-admin users see the admin note and never request internal tables', async () => {
		setUser(false);

		render(SystemTab);

		expect(await screen.findByTestId('internal-tables-admin-required')).toHaveTextContent(
			'requires the admin account'
		);
		expect(mockListInternalPostgresTables).not.toHaveBeenCalled();
		expect(screen.queryByLabelText('Onboard table default.analyses')).toBeNull();
	});

	test('fetches internal tables once the admin user resolves after mount', async () => {
		setUser(null);

		render(SystemTab);

		expect(await screen.findByTestId('internal-tables-admin-required')).toBeVisible();
		expect(mockListInternalPostgresTables).not.toHaveBeenCalled();

		setUser(true);

		const groupToggle = await screen.findByRole('button', { name: /Namespace tables: default/i });
		expect(groupToggle).toBeVisible();
		expect(screen.queryByTestId('internal-tables-admin-required')).toBeNull();
		expect(mockListInternalPostgresTables).toHaveBeenCalledTimes(1);
	});

	test('drops the table list when the user is no longer the admin', async () => {
		render(SystemTab);

		const groupToggle = await screen.findByRole('button', { name: /Namespace tables: default/i });
		expect(groupToggle).toBeVisible();

		setUser(false);

		expect(await screen.findByTestId('internal-tables-admin-required')).toBeVisible();
		expect(screen.queryByRole('button', { name: /Namespace tables: default/i })).toBeNull();
		expect(mockListInternalPostgresTables).toHaveBeenCalledTimes(1);
	});
});
