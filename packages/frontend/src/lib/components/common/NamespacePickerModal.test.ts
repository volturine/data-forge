import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { SvelteMap } from 'svelte/reactivity';
import { onDestroy } from 'svelte';
import { okAsync } from 'neverthrow';
import type { NamespaceStoragePlan } from '#lib/api/namespaces.js';

const mocks = vi.hoisted(() => ({
	createQuery: vi.fn(),
	listNamespaces: vi.fn(),
	previewNamespaceStorage: vi.fn()
}));

vi.mock('@tanstack/svelte-query', () => ({ createQuery: mocks.createQuery }));
vi.mock('#lib/api/namespaces.js', () => ({
	listNamespaces: mocks.listNamespaces,
	previewNamespaceStorage: mocks.previewNamespaceStorage
}));

import NamespacePickerModal from './NamespacePickerModal.svelte';

interface QueryOptions {
	queryKey: readonly unknown[];
	queryFn: () => Promise<unknown>;
	enabled?: boolean;
}

interface QueryState {
	data: unknown;
	isLoading: boolean;
	isError: boolean;
}

interface PickerProps {
	open: boolean;
	selected: string;
	onSelect: (value: string) => void | Promise<void>;
	onSelectError?: (message: string) => void;
	onClose: () => void;
}

const emptyQueryState: QueryState = { data: undefined, isLoading: false, isError: false };
const loadingQueryState: QueryState = { data: undefined, isLoading: true, isError: false };

function queryKey(options: QueryOptions): string {
	return JSON.stringify(options.queryKey) ?? '';
}

function createQueryMock(getOptions: () => QueryOptions) {
	const states = new SvelteMap<string, QueryState>();
	const scheduled = new Set<string>();
	let destroyed = false;

	onDestroy(() => {
		destroyed = true;
		scheduled.clear();
	});

	function start(options: QueryOptions, key: string): void {
		if (!options.enabled || destroyed || states.has(key) || scheduled.has(key)) return;
		scheduled.add(key);
		queueMicrotask(() => {
			const currentOptions = getOptions();
			if (
				destroyed ||
				!currentOptions.enabled ||
				queryKey(currentOptions) !== key ||
				states.has(key)
			) {
				scheduled.delete(key);
				return;
			}

			states.set(key, { data: undefined, isLoading: true, isError: false });
			void currentOptions.queryFn().then(
				(data) => {
					if (!destroyed) states.set(key, { data, isLoading: false, isError: false });
					scheduled.delete(key);
				},
				() => {
					if (!destroyed) states.set(key, { data: undefined, isLoading: false, isError: true });
					scheduled.delete(key);
				}
			);
		});
	}

	function currentState(): QueryState {
		const options = getOptions();
		const key = queryKey(options);
		const current = states.get(key);
		if (options.enabled && !current) start(options, key);
		if (current) return current;
		if (options.enabled) return loadingQueryState;
		return emptyQueryState;
	}

	async function refetch(): Promise<void> {
		const options = getOptions();
		const key = queryKey(options);
		if (!options.enabled || destroyed) return;
		scheduled.delete(key);
		states.set(key, { data: undefined, isLoading: true, isError: false });
		try {
			const data = await options.queryFn();
			if (!destroyed) states.set(key, { data, isLoading: false, isError: false });
		} catch {
			if (!destroyed) states.set(key, { data: undefined, isLoading: false, isError: true });
		}
	}

	return {
		get data() {
			return currentState().data;
		},
		get isLoading() {
			return currentState().isLoading;
		},
		get isError() {
			return currentState().isError;
		},
		refetch
	};
}

function makeStoragePlan(name: string): NamespaceStoragePlan {
	return {
		name,
		bucket: name,
		uploads_root: `s3://${name}/uploads`,
		clean_root: `s3://${name}/clean`,
		exports_root: `s3://${name}/exports`,
		runtime_artifacts_root: `s3://${name}/runtime`,
		rules: 'test plan'
	};
}

function renderPicker(props: Partial<PickerProps> = {}) {
	return render(NamespacePickerModal, {
		props: {
			open: true,
			selected: 'default',
			onSelect: vi.fn(),
			onClose: vi.fn(),
			...props
		}
	});
}

beforeEach(() => {
	vi.clearAllMocks();
	mocks.createQuery.mockImplementation((getOptions: () => QueryOptions) =>
		createQueryMock(getOptions)
	);
	mocks.listNamespaces.mockImplementation(() => okAsync({ namespaces: ['default'] }));
	mocks.previewNamespaceStorage.mockImplementation((name: string) =>
		okAsync(makeStoragePlan(name))
	);
});

afterEach(() => {
	vi.restoreAllMocks();
});

describe('NamespacePickerModal', () => {
	test('creates a valid namespace only after showing its storage plan', async () => {
		const onSelect = vi.fn();
		const onClose = vi.fn();
		renderPicker({ onSelect, onClose });

		await fireEvent.click(screen.getByRole('button', { name: 'New namespace' }));
		const name = screen.getByRole('textbox', { name: 'Name' });
		expect(name).toHaveFocus();
		await fireEvent.input(name, { target: { value: 'analytics_1' } });

		await screen.findByText('S3 bucket (root): analytics_1');
		expect(mocks.previewNamespaceStorage).toHaveBeenCalledWith('analytics_1');
		const create = screen.getByRole('button', { name: 'Create namespace' });
		expect(create).toBeEnabled();

		await fireEvent.click(create);
		await waitFor(() => expect(onSelect).toHaveBeenCalledWith('analytics_1'));
		expect(onClose).toHaveBeenCalledOnce();
	});

	test('rejects invalid names without requesting a storage plan', async () => {
		renderPicker();
		await fireEvent.click(screen.getByRole('button', { name: 'New namespace' }));
		const name = screen.getByRole('textbox', { name: 'Name' });
		expect(name).toHaveAttribute('aria-describedby', 'namespace-create-name-rules');
		expect(screen.getByText(/3–63 characters/)).toBeInTheDocument();
		await fireEvent.input(name, {
			target: { value: 'Bad_Name' }
		});

		expect(await screen.findByRole('alert')).toHaveTextContent('lowercase letters');
		expect(screen.getAllByText(/3–63 characters/)).toHaveLength(1);
		expect(screen.getByRole('button', { name: 'Create namespace' })).toBeDisabled();
		expect(mocks.previewNamespaceStorage).not.toHaveBeenCalled();
	});

	test('blocks an existing namespace name with an explanation', async () => {
		mocks.listNamespaces.mockImplementation(() =>
			okAsync({ namespaces: ['default', 'already-there'] })
		);
		renderPicker();
		await fireEvent.click(screen.getByRole('button', { name: 'New namespace' }));
		await fireEvent.input(screen.getByRole('textbox', { name: 'Name' }), {
			target: { value: 'already-there' }
		});

		expect(await screen.findByRole('alert')).toHaveTextContent('already exists');
		expect(screen.getByRole('button', { name: 'Create namespace' })).toBeDisabled();
		expect(mocks.previewNamespaceStorage).not.toHaveBeenCalled();
	});

	test('closes without switching when the current namespace is selected', async () => {
		const onSelect = vi.fn();
		const onClose = vi.fn();
		renderPicker({ onSelect, onClose });

		await fireEvent.click(
			await screen.findByRole('button', { name: /default.*Current namespace/ })
		);

		expect(onSelect).not.toHaveBeenCalled();
		expect(onClose).toHaveBeenCalledOnce();
	});

	test('keeps the dialog open and blocks close actions while selection is pending', async () => {
		let resolveSelection: () => void = () => undefined;
		const pendingSelection = new Promise<void>((resolve) => {
			resolveSelection = resolve;
		});
		const onSelect = vi.fn(() => pendingSelection);
		const onClose = vi.fn();
		renderPicker({ onSelect, onClose });

		await fireEvent.click(screen.getByRole('button', { name: 'New namespace' }));
		await fireEvent.input(screen.getByRole('textbox', { name: 'Name' }), {
			target: { value: 'pending-space' }
		});
		const create = await screen.findByRole('button', { name: 'Create namespace' });
		await waitFor(() => expect(create).toBeEnabled());
		await fireEvent.click(create);

		expect(await screen.findByText('Preparing namespace…')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Close namespace picker' })).toBeDisabled();
		expect(screen.getByRole('button', { name: 'Back to namespaces' })).toBeDisabled();
		await fireEvent.keyDown(window, { key: 'Escape' });
		expect(onClose).not.toHaveBeenCalled();
		expect(screen.getByRole('dialog')).toBeInTheDocument();

		resolveSelection();
		await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
	});

	test('shows async selection errors and preserves both names for retry', async () => {
		const onSelect = vi.fn().mockRejectedValue(new Error('registration failed'));
		const onSelectError = vi.fn();
		const onClose = vi.fn();
		renderPicker({ onSelect, onSelectError, onClose });

		await fireEvent.input(screen.getByRole('textbox', { name: 'Search namespaces' }), {
			target: { value: 'retry_space' }
		});
		await fireEvent.click(screen.getByRole('button', { name: 'New namespace' }));
		const name = screen.getByRole('textbox', { name: 'Name' });
		expect(name).toHaveValue('retry_space');
		await screen.findByText('S3 bucket (root): retry_space');
		await fireEvent.click(screen.getByRole('button', { name: 'Create namespace' }));

		expect(await screen.findByRole('alert')).toHaveTextContent('registration failed');
		expect(name).toHaveValue('retry_space');
		expect(onSelectError).toHaveBeenCalledWith('registration failed');
		expect(onClose).not.toHaveBeenCalled();

		await fireEvent.click(screen.getByRole('button', { name: 'Back to namespaces' }));
		const search = screen.getByRole('textbox', { name: 'Search namespaces' });
		expect(search).toHaveValue('retry_space');
		expect(search).toHaveFocus();
		await fireEvent.click(screen.getByRole('button', { name: 'New namespace' }));
		const retryName = screen.getByRole('textbox', { name: 'Name' });
		expect(retryName).toHaveValue('retry_space');
		expect(retryName).toHaveFocus();
	});

	test('shows synchronous selection errors inside the dialog', async () => {
		const onSelect = vi.fn(() => {
			throw new Error('switch failed');
		});
		const onSelectError = vi.fn();
		mocks.listNamespaces.mockImplementation(() =>
			okAsync({ namespaces: ['default', 'team-data'] })
		);
		renderPicker({
			selected: 'default',
			onSelect,
			onSelectError
		});

		await fireEvent.click(await screen.findByRole('button', { name: 'team-data' }));

		expect(await screen.findByRole('alert')).toHaveTextContent('switch failed');
		expect(onSelectError).toHaveBeenCalledWith('switch failed');
		expect(screen.getByRole('dialog')).toBeInTheDocument();
	});
});
