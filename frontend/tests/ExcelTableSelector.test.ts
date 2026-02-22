import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { okAsync } from 'neverthrow';
import ExcelTableSelector from '$lib/components/common/ExcelTableSelector.svelte';

const preflightResponse = {
	preflight_id: 'preflight-1',
	sheet_name: 'Sheet1',
	sheet_names: ['Sheet1'],
	tables: { Sheet1: ['Table1'] },
	named_ranges: ['Range1'],
	preview: [['a', 'b']],
	start_row: 0,
	start_col: 0,
	end_col: 1,
	detected_end_row: 1
};

const previewResponse = {
	preview: [['c', 'd']],
	sheet_name: 'Sheet1',
	start_row: 0,
	start_col: 0,
	end_col: 1,
	detected_end_row: 1
};

vi.mock('$lib/api/excel', () => {
	const preflightExcel = vi.fn(() => okAsync(preflightResponse));
	const preflightExcelFromPath = vi.fn(() => okAsync(preflightResponse));
	const previewExcel = vi.fn(() => okAsync(previewResponse));
	return { preflightExcel, preflightExcelFromPath, previewExcel };
});

describe('ExcelTableSelector', () => {
	it('does not refresh preview on manual inputs', async () => {
		const api = await import('$lib/api/excel');
		render(ExcelTableSelector, {
			props: {
				mode: 'config',
				filePath: '/tmp/file.xlsx',
				preflightId: 'preflight-1'
			}
		});

		await waitFor(() => {
			expect(screen.getByText('Start row:')).toBeTruthy();
		});

		await fireEvent.input(screen.getByLabelText('Manual Range'), {
			target: { value: 'A1:B2' }
		});
		await fireEvent.blur(screen.getByLabelText('Manual Range'));

		await fireEvent.input(screen.getByLabelText('Start row'), { target: { value: '2' } });
		await fireEvent.blur(screen.getByLabelText('Start row'));

		await fireEvent.input(screen.getByLabelText('Start col'), { target: { value: 'B' } });
		await fireEvent.blur(screen.getByLabelText('Start col'));

		await fireEvent.input(screen.getByLabelText('End col'), { target: { value: 'D' } });
		await fireEvent.blur(screen.getByLabelText('End col'));

		await fireEvent.input(screen.getByLabelText('End row'), { target: { value: '5' } });
		await fireEvent.blur(screen.getByLabelText('End row'));

		await fireEvent.click(screen.getByLabelText('First row is header'));

		expect(api.previewExcel).not.toHaveBeenCalled();
	});

	it('refresh button triggers preview when preflight exists', async () => {
		const api = await import('$lib/api/excel');
		render(ExcelTableSelector, {
			props: {
				mode: 'config',
				filePath: '/tmp/file.xlsx',
				preflightId: 'preflight-1'
			}
		});

		await waitFor(() => {
			expect(screen.getByText('Start row:')).toBeTruthy();
		});

		await fireEvent.click(screen.getByText('Refresh preview'));

		await waitFor(() => {
			expect(api.previewExcel).toHaveBeenCalledTimes(1);
		});
	});
});
