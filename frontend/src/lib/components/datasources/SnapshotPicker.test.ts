import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import { okAsync } from 'neverthrow';
import SnapshotPicker from './SnapshotPicker.svelte';

const mockApiRequest = vi.fn();
vi.mock('$lib/api/client', () => ({
	apiRequest: (...args: unknown[]) => mockApiRequest(...args)
}));

const mockListEngineRuns = vi.fn();
vi.mock('$lib/api/engine-runs', () => ({
	listEngineRuns: (...args: unknown[]) => mockListEngineRuns(...args)
}));

function renderPicker(props: Record<string, unknown> = {}) {
	return render(SnapshotPicker, {
		props: {
			datasourceId: 'ds-1',
			datasourceConfig: {},
			...props
		}
	});
}

const JUN15 = new Date('2024-06-15T12:00:00Z').getTime();
const JUN15_LATE = new Date('2024-06-15T18:30:00Z').getTime();
const JUN20 = new Date('2024-06-20T10:00:00Z').getTime();

function makeSnapshots(
	items: Array<{
		id?: string;
		ts?: number;
		op?: string | null;
		current?: boolean;
	}> = []
) {
	return {
		snapshots: items.map((item, i) => ({
			snapshot_id: item.id ?? `snap-${i}`,
			timestamp_ms: item.ts ?? JUN15 + i * 1000,
			operation: item.op ?? 'append',
			is_current: item.current ?? i === 0
		}))
	};
}

beforeEach(() => {
	mockApiRequest.mockReset();
	mockListEngineRuns.mockReset();
});

describe('SnapshotPicker', () => {
	describe('trigger button', () => {
		test('renders trigger with label', () => {
			renderPicker();
			const trigger = screen.getByRole('button');
			expect(trigger).toHaveTextContent('Time Travel');
		});

		test('renders custom label', () => {
			renderPicker({ label: 'Snapshots' });
			expect(screen.getByRole('button')).toHaveTextContent('Snapshots');
		});

		test('shows Latest badge when no snapshot selected', () => {
			renderPicker();
			expect(screen.getByText('Latest')).toBeInTheDocument();
		});

		test('shows snapshot id badge when snapshot selected via config', () => {
			renderPicker({
				datasourceConfig: {
					snapshot_id: 'snap-abc',
					snapshot_timestamp_ms: 1700000000000
				}
			});
			expect(screen.getByText('snap-abc')).toBeInTheDocument();
		});
	});

	describe('open/close', () => {
		test('popover is closed by default', () => {
			renderPicker();
			expect(screen.queryByText('Loading snapshots...')).not.toBeInTheDocument();
			expect(screen.queryByText('Current: Latest')).not.toBeInTheDocument();
		});

		test('opens popover on trigger click and loads snapshots', async () => {
			mockApiRequest.mockReturnValue(okAsync({ snapshots: [] }));
			renderPicker();
			await fireEvent.click(screen.getByRole('button'));
			expect(screen.getByText('No snapshots found.')).toBeInTheDocument();
		});

		test('shows loading state while fetching', async () => {
			let _resolve: (v: unknown) => void;
			const pending = new Promise((r) => {
				_resolve = r;
			});
			mockApiRequest.mockReturnValue({
				match: (onOk: (v: unknown) => void, _onErr: (e: unknown) => void) => {
					pending.then(() => onOk({ snapshots: [] }));
				}
			});
			renderPicker();
			await fireEvent.click(screen.getByRole('button'));
			expect(screen.getByText('Loading snapshots...')).toBeInTheDocument();
		});

		test('shows error when snapshot fetch fails', async () => {
			mockApiRequest.mockReturnValue({
				match: (_onOk: unknown, onErr: (e: unknown) => void) => {
					onErr({ message: 'Network error' });
				}
			});
			renderPicker();
			await fireEvent.click(screen.getByRole('button'));
			expect(screen.getByText('Network error')).toBeInTheDocument();
		});
	});

	describe('latest reset', () => {
		test('shows Latest reset button when snapshot is selected', async () => {
			mockApiRequest.mockReturnValue(
				okAsync({
					snapshots: [
						{
							snapshot_id: 'snap-1',
							timestamp_ms: 1700000000000,
							operation: 'append',
							is_current: true
						}
					]
				})
			);
			const onConfigChange = vi.fn();
			renderPicker({
				datasourceConfig: {
					snapshot_id: 'snap-1',
					snapshot_timestamp_ms: 1700000000000
				},
				onConfigChange
			});
			await fireEvent.click(screen.getByRole('button'));
			const latestButtons = screen.getAllByText('Latest');
			const resetButton = latestButtons.find(
				(el) => el.tagName === 'BUTTON' && el.closest('[role="presentation"]') === null
			);
			expect(resetButton).toBeDefined();
		});

		test('clicking Latest reset fires onConfigChange and onSelect with null', async () => {
			mockApiRequest.mockReturnValue(
				okAsync(makeSnapshots([{ id: 'snap-1', ts: JUN15, current: true }]))
			);
			const onConfigChange = vi.fn();
			const onSelect = vi.fn();
			renderPicker({
				datasourceConfig: {
					snapshot_id: 'snap-1',
					snapshot_timestamp_ms: JUN15
				},
				onConfigChange,
				onSelect
			});
			await fireEvent.click(screen.getByRole('button'));
			const latestButtons = screen.getAllByText('Latest');
			const resetButton = latestButtons.find(
				(el) => el.tagName === 'BUTTON' && el.closest('.engine-header') === null
			);
			expect(resetButton).toBeDefined();
			await fireEvent.click(resetButton!);
			expect(onConfigChange).toHaveBeenCalledOnce();
			const config = onConfigChange.mock.calls[0][0];
			expect(config.snapshot_id).toBeUndefined();
			expect(config.snapshot_timestamp_ms).toBeUndefined();
			expect(onSelect).toHaveBeenCalledWith(null, undefined);
		});
	});

	describe('missing snapshot warning', () => {
		test('shows warning when selected snapshot is not in list', async () => {
			mockApiRequest.mockReturnValue(okAsync({ snapshots: [] }));
			renderPicker({
				datasourceConfig: {
					snapshot_id: 'snap-gone',
					snapshot_timestamp_ms: 1700000000000
				}
			});
			await fireEvent.click(screen.getByRole('button'));
			expect(screen.getByText(/Selected snapshot #snap-gone no longer exists/)).toBeInTheDocument();
		});

		test('shows switch to latest button in warning', async () => {
			mockApiRequest.mockReturnValue(okAsync({ snapshots: [] }));
			renderPicker({
				datasourceConfig: {
					snapshot_id: 'snap-gone',
					snapshot_timestamp_ms: 1700000000000
				}
			});
			await fireEvent.click(screen.getByRole('button'));
			expect(screen.getByText('Switch to latest')).toBeInTheDocument();
		});

		test('calls onConfigChange with null snapshot on switch to latest', async () => {
			mockApiRequest.mockReturnValue(okAsync({ snapshots: [] }));
			const onConfigChange = vi.fn();
			const onSelect = vi.fn();
			renderPicker({
				datasourceConfig: {
					snapshot_id: 'snap-gone',
					snapshot_timestamp_ms: 1700000000000
				},
				onConfigChange,
				onSelect
			});
			await fireEvent.click(screen.getByRole('button'));
			await fireEvent.click(screen.getByText('Switch to latest'));
			expect(onConfigChange).toHaveBeenCalled();
			const config = onConfigChange.mock.calls[0][0];
			expect(config.snapshot_id).toBeUndefined();
			expect(onSelect).toHaveBeenCalledWith(null, undefined);
		});
	});

	describe('month navigation', () => {
		test('shows month navigation buttons and current month', async () => {
			mockApiRequest.mockReturnValue(
				okAsync(makeSnapshots([{ id: 's1', ts: JUN15, current: true }]))
			);
			renderPicker();
			await fireEvent.click(screen.getByRole('button'));
			expect(screen.getByText('2024-06')).toBeInTheDocument();
			expect(screen.getByText('←')).toBeInTheDocument();
			expect(screen.getByText('→')).toBeInTheDocument();
		});

		test('renders calendar day headers', async () => {
			mockApiRequest.mockReturnValue(
				okAsync(makeSnapshots([{ id: 's1', ts: JUN15, current: true }]))
			);
			renderPicker();
			await fireEvent.click(screen.getByRole('button'));
			expect(screen.getByText('Mo')).toBeInTheDocument();
			expect(screen.getByText('Su')).toBeInTheDocument();
		});

		test('shows day with snapshot count badge', async () => {
			const snapshots = Array.from({ length: 42 }, (_, i) => ({
				id: `s${i}`,
				ts: JUN15 + i * 1000,
				current: i === 0
			}));
			mockApiRequest.mockReturnValue(okAsync(makeSnapshots(snapshots)));
			renderPicker();
			await fireEvent.click(screen.getByRole('button'));
			expect(screen.getByText('42')).toBeInTheDocument();
		});

		test('clicking → advances to next month', async () => {
			mockApiRequest.mockReturnValue(
				okAsync(makeSnapshots([{ id: 's1', ts: JUN15, current: true }]))
			);
			const onUiChange = vi.fn();
			renderPicker({ onUiChange });
			await fireEvent.click(screen.getByRole('button'));
			expect(screen.getByText('2024-06')).toBeInTheDocument();

			const nextBtn = screen.getByText('→');
			await fireEvent.click(nextBtn);
			await tick();

			const monthCall = onUiChange.mock.calls.find(
				(c: Array<Record<string, unknown>>) => c[0].month === '2024-07'
			);
			expect(monthCall).toBeDefined();
		});

		test('clicking ← goes to previous month', async () => {
			mockApiRequest.mockReturnValue(
				okAsync(makeSnapshots([{ id: 's1', ts: JUN15, current: true }]))
			);
			const onUiChange = vi.fn();
			renderPicker({ onUiChange });
			await fireEvent.click(screen.getByRole('button'));
			expect(screen.getByText('2024-06')).toBeInTheDocument();

			const prevBtn = screen.getByText('←');
			await fireEvent.click(prevBtn);
			await tick();

			const monthCall = onUiChange.mock.calls.find(
				(c: Array<Record<string, unknown>>) => c[0].month === '2024-05'
			);
			expect(monthCall).toBeDefined();
		});

		test('month navigation fires onUiChange with new month', async () => {
			mockApiRequest.mockReturnValue(
				okAsync(makeSnapshots([{ id: 's1', ts: JUN15, current: true }]))
			);
			const onUiChange = vi.fn();
			renderPicker({ onUiChange });
			await fireEvent.click(screen.getByRole('button'));
			await fireEvent.click(screen.getByText('→'));
			await tick();
			const calls = onUiChange.mock.calls;
			const monthCall = calls.find((c: Array<Record<string, unknown>>) => c[0].month === '2024-07');
			expect(monthCall).toBeDefined();
		});
	});

	describe('day selection', () => {
		test('shows prompt when no day selected', async () => {
			mockApiRequest.mockReturnValue(
				okAsync(makeSnapshots([{ id: 's1', ts: JUN15, current: true }]))
			);
			renderPicker();
			await fireEvent.click(screen.getByRole('button'));
			expect(screen.getByText('Select a day to view builds.')).toBeInTheDocument();
		});

		test('clicking a day with snapshots shows snapshot list', async () => {
			mockApiRequest.mockReturnValue(
				okAsync(
					makeSnapshots([
						{ id: 'snap-a', ts: JUN15, current: true },
						{ id: 'snap-b', ts: JUN15_LATE, current: false }
					])
				)
			);
			renderPicker();
			await fireEvent.click(screen.getByRole('button'));
			expect(screen.getByText('Select a day to view builds.')).toBeInTheDocument();

			const dayButton = screen.getByText('15').closest('button');
			expect(dayButton).toBeTruthy();
			await fireEvent.click(dayButton!);

			expect(screen.queryByText('Select a day to view builds.')).not.toBeInTheDocument();
			const buttons = screen.getAllByRole('button');
			const snapshotButtons = buttons.filter(
				(btn) => btn.closest('[style]') || btn.textContent?.match(/\d{2}:\d{2}:\d{2}/)
			);
			expect(snapshotButtons.length).toBeGreaterThanOrEqual(1);
		});

		test('clicking a day fires onUiChange with day key', async () => {
			mockApiRequest.mockReturnValue(
				okAsync(makeSnapshots([{ id: 'snap-a', ts: JUN20, current: true }]))
			);
			const onUiChange = vi.fn();
			renderPicker({ onUiChange });
			await fireEvent.click(screen.getByRole('button'));

			const dayButton = screen.getByText('20').closest('button');
			await fireEvent.click(dayButton!);

			const dayCalls = onUiChange.mock.calls.filter(
				(c: Array<Record<string, unknown>>) => c[0].day === '2024-06-20'
			);
			expect(dayCalls.length).toBeGreaterThanOrEqual(1);
		});

		test('clicking a day with no snapshots does nothing', async () => {
			mockApiRequest.mockReturnValue(
				okAsync(makeSnapshots([{ id: 'snap-a', ts: JUN15, current: true }]))
			);
			const onUiChange = vi.fn();
			renderPicker({ onUiChange });
			await fireEvent.click(screen.getByRole('button'));

			const emptyDayButton = screen.getByText('3').closest('button');
			await fireEvent.click(emptyDayButton!);

			expect(screen.getByText('Select a day to view builds.')).toBeInTheDocument();
		});
	});

	describe('snapshot selection', () => {
		test('clicking a snapshot row fires onConfigChange and onSelect with snapshot data', async () => {
			mockApiRequest.mockReturnValue(
				okAsync(
					makeSnapshots([
						{ id: 'snap-a', ts: JUN15, current: true },
						{ id: 'snap-b', ts: JUN15_LATE, current: false }
					])
				)
			);
			const onConfigChange = vi.fn();
			const onSelect = vi.fn();
			renderPicker({ onConfigChange, onSelect });

			await fireEvent.click(screen.getByRole('button'));
			const dayButton = screen.getByText('15').closest('button');
			await fireEvent.click(dayButton!);

			const allButtons = screen.getAllByRole('button');
			const timeButtons = allButtons.filter((btn) => btn.textContent?.match(/\d{2}:\d{2}:\d{2}/));
			expect(timeButtons.length).toBeGreaterThanOrEqual(1);
			await fireEvent.click(timeButtons[0]);

			expect(onConfigChange).toHaveBeenCalledOnce();
			const config = onConfigChange.mock.calls[0][0];
			expect(typeof config.snapshot_id).toBe('string');
			expect(config.snapshot_id).toMatch(/^snap-/);
			expect(typeof config.snapshot_timestamp_ms).toBe('number');

			expect(onSelect).toHaveBeenCalledOnce();
			expect(onSelect.mock.calls[0][0]).toMatch(/^snap-/);
			expect(typeof onSelect.mock.calls[0][1]).toBe('number');
		});
	});

	describe('delete flow', () => {
		test('shows delete button when showDelete=true and snapshot is not current', async () => {
			mockApiRequest.mockReturnValue(
				okAsync(
					makeSnapshots([
						{ id: 'snap-a', ts: JUN15, current: true },
						{ id: 'snap-b', ts: JUN15_LATE, current: false }
					])
				)
			);
			renderPicker({ showDelete: true });
			await fireEvent.click(screen.getByRole('button'));
			const dayButton = screen.getByText('15').closest('button');
			await fireEvent.click(dayButton!);

			expect(screen.getByLabelText('Delete snapshot')).toBeInTheDocument();
		});

		test('does not show delete button for current snapshot', async () => {
			mockApiRequest.mockReturnValue(
				okAsync(makeSnapshots([{ id: 'snap-a', ts: JUN15, current: true }]))
			);
			renderPicker({ showDelete: true });
			await fireEvent.click(screen.getByRole('button'));
			const dayButton = screen.getByText('15').closest('button');
			await fireEvent.click(dayButton!);

			expect(screen.queryByLabelText('Delete snapshot')).not.toBeInTheDocument();
		});

		test('clicking delete button shows confirm/cancel', async () => {
			mockApiRequest.mockReturnValue(
				okAsync(
					makeSnapshots([
						{ id: 'snap-a', ts: JUN15, current: true },
						{ id: 'snap-b', ts: JUN15_LATE, current: false }
					])
				)
			);
			renderPicker({ showDelete: true });
			await fireEvent.click(screen.getByRole('button'));
			const dayButton = screen.getByText('15').closest('button');
			await fireEvent.click(dayButton!);

			await fireEvent.click(screen.getByLabelText('Delete snapshot'));

			expect(screen.getByText('Confirm')).toBeInTheDocument();
			expect(screen.getByText('Cancel')).toBeInTheDocument();
		});

		test('clicking cancel hides confirm/cancel and restores delete button', async () => {
			mockApiRequest.mockReturnValue(
				okAsync(
					makeSnapshots([
						{ id: 'snap-a', ts: JUN15, current: true },
						{ id: 'snap-b', ts: JUN15_LATE, current: false }
					])
				)
			);
			renderPicker({ showDelete: true });
			await fireEvent.click(screen.getByRole('button'));
			const dayButton = screen.getByText('15').closest('button');
			await fireEvent.click(dayButton!);
			await fireEvent.click(screen.getByLabelText('Delete snapshot'));

			expect(screen.getByText('Confirm')).toBeInTheDocument();
			await fireEvent.click(screen.getByText('Cancel'));

			expect(screen.queryByText('Confirm')).not.toBeInTheDocument();
			expect(screen.getByLabelText('Delete snapshot')).toBeInTheDocument();
		});

		test('does not show delete buttons when showDelete=false', async () => {
			mockApiRequest.mockReturnValue(
				okAsync(
					makeSnapshots([
						{ id: 'snap-a', ts: JUN15, current: true },
						{ id: 'snap-b', ts: JUN15_LATE, current: false }
					])
				)
			);
			renderPicker({ showDelete: false });
			await fireEvent.click(screen.getByRole('button'));
			const dayButton = screen.getByText('15').closest('button');
			await fireEvent.click(dayButton!);

			expect(screen.queryByLabelText('Delete snapshot')).not.toBeInTheDocument();
		});
	});

	describe('persistOpen and onUiChange', () => {
		test('persistOpen restores open state from config', () => {
			mockApiRequest.mockReturnValue(okAsync(makeSnapshots([])));
			renderPicker({
				persistOpen: true,
				datasourceConfig: {
					time_travel_ui: { open: true }
				}
			});
			expect(screen.getByText('Current: Latest')).toBeInTheDocument();
		});

		test('persistOpen false does not auto-open', () => {
			renderPicker({
				persistOpen: false,
				datasourceConfig: {}
			});
			expect(screen.queryByText('Current: Latest')).not.toBeInTheDocument();
		});

		test('toggle fires onUiChange with open flag when persistOpen', async () => {
			mockApiRequest.mockReturnValue(okAsync(makeSnapshots([])));
			const onUiChange = vi.fn();
			renderPicker({ persistOpen: true, onUiChange });
			await fireEvent.click(screen.getByRole('button'));
			const openCall = onUiChange.mock.calls.find(
				(c: Array<Record<string, unknown>>) => c[0].open === true
			);
			expect(openCall).toBeDefined();
		});
	});
});
