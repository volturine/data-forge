import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import AnalysisCard from './AnalysisCard.svelte';
import type { AnalysisGalleryItem } from '$lib/types/analysis';
import { goto } from '$app/navigation';

vi.mock('$app/navigation');

describe('AnalysisCard', () => {
	const mockAnalysis: AnalysisGalleryItem = {
		id: 'test-123',
		name: 'Test Analysis',
		thumbnail: 'https://example.com/thumb.jpg',
		created_at: '2024-01-15T10:00:00Z',
		updated_at: '2024-01-16T15:30:00Z',
		row_count: 1000,
		column_count: 5
	};

	const mockAnalysisNoThumbnail: AnalysisGalleryItem = {
		id: 'test-456',
		name: 'Analysis Without Thumbnail',
		thumbnail: null,
		created_at: '2024-01-10T08:00:00Z',
		updated_at: '2024-01-10T09:00:00Z',
		row_count: null,
		column_count: null
	};

	let onDeleteMock: ReturnType<typeof vi.fn>;

	beforeEach(() => {
		onDeleteMock = vi.fn();
		vi.clearAllMocks();
	});

	describe('rendering with analysis data', () => {
		it('should render analysis name', () => {
			render(AnalysisCard, {
				props: {
					analysis: mockAnalysis,
					onDelete: onDeleteMock
				}
			});

			expect(screen.getByText('Test Analysis')).toBeInTheDocument();
		});

		it('should render thumbnail when available', () => {
			render(AnalysisCard, {
				props: {
					analysis: mockAnalysis,
					onDelete: onDeleteMock
				}
			});

			const img = screen.getByAltText('Test Analysis');
			expect(img).toBeInTheDocument();
			expect(img).toHaveAttribute('src', 'https://example.com/thumb.jpg');
		});

		it('should render placeholder when thumbnail is null', () => {
			const { container } = render(AnalysisCard, {
				props: {
					analysis: mockAnalysisNoThumbnail,
					onDelete: onDeleteMock
				}
			});

			expect(screen.queryByAltText('Analysis Without Thumbnail')).not.toBeInTheDocument();
			expect(container.querySelector('.placeholder')).toBeInTheDocument();
		});

		it('should display row count when available', () => {
			render(AnalysisCard, {
				props: {
					analysis: mockAnalysis,
					onDelete: onDeleteMock
				}
			});

			expect(screen.getByText('1,000 rows')).toBeInTheDocument();
		});

		it('should display column count when available', () => {
			render(AnalysisCard, {
				props: {
					analysis: mockAnalysis,
					onDelete: onDeleteMock
				}
			});

			expect(screen.getByText('5 cols')).toBeInTheDocument();
		});

		it('should not display stats when row and column count are null', () => {
			const { container } = render(AnalysisCard, {
				props: {
					analysis: mockAnalysisNoThumbnail,
					onDelete: onDeleteMock
				}
			});

			expect(screen.queryByText(/rows/)).not.toBeInTheDocument();
			expect(screen.queryByText(/cols/)).not.toBeInTheDocument();
			expect(container.querySelector('.stats')).not.toBeInTheDocument();
		});

		it('should format updated date correctly', () => {
			render(AnalysisCard, {
				props: {
					analysis: mockAnalysis,
					onDelete: onDeleteMock
				}
			});

			expect(screen.getByText(/Updated Jan 16, 2024/)).toBeInTheDocument();
		});

		it('should render delete button', () => {
			render(AnalysisCard, {
				props: {
					analysis: mockAnalysis,
					onDelete: onDeleteMock
				}
			});

			expect(screen.getByLabelText('Delete analysis')).toBeInTheDocument();
		});
	});

	describe('delete button click', () => {
		it('should call onDelete with analysis id when delete button is clicked', async () => {
			render(AnalysisCard, {
				props: {
					analysis: mockAnalysis,
					onDelete: onDeleteMock
				}
			});

			const deleteButton = screen.getByLabelText('Delete analysis');
			await fireEvent.click(deleteButton);

			expect(onDeleteMock).toHaveBeenCalledTimes(1);
			expect(onDeleteMock).toHaveBeenCalledWith('test-123');
		});

		it('should not navigate when delete button is clicked', async () => {
			render(AnalysisCard, {
				props: {
					analysis: mockAnalysis,
					onDelete: onDeleteMock
				}
			});

			const deleteButton = screen.getByLabelText('Delete analysis');
			await fireEvent.click(deleteButton);

			expect(goto).not.toHaveBeenCalled();
		});
	});

	describe('navigation to editor', () => {
		it('should navigate to analysis editor when card is clicked', async () => {
			const { container } = render(AnalysisCard, {
				props: {
					analysis: mockAnalysis,
					onDelete: onDeleteMock
				}
			});

			const card = container.querySelector('.card');
			await fireEvent.click(card!);

			expect(goto).toHaveBeenCalledTimes(1);
			expect(goto).toHaveBeenCalledWith('/analysis/test-123');
		});

		it('should navigate when Enter key is pressed on card', async () => {
			const { container } = render(AnalysisCard, {
				props: {
					analysis: mockAnalysis,
					onDelete: onDeleteMock
				}
			});

			const card = container.querySelector('.card');
			await fireEvent.keyPress(card!, { key: 'Enter', code: 'Enter' });

			expect(goto).toHaveBeenCalledTimes(1);
			expect(goto).toHaveBeenCalledWith('/analysis/test-123');
		});

		it('should navigate when Space key is pressed on card', async () => {
			const { container } = render(AnalysisCard, {
				props: {
					analysis: mockAnalysis,
					onDelete: onDeleteMock
				}
			});

			const card = container.querySelector('.card');
			await fireEvent.keyPress(card!, { key: ' ', code: 'Space' });

			expect(goto).toHaveBeenCalledTimes(1);
			expect(goto).toHaveBeenCalledWith('/analysis/test-123');
		});

		it('should not navigate when other keys are pressed', async () => {
			const { container } = render(AnalysisCard, {
				props: {
					analysis: mockAnalysis,
					onDelete: onDeleteMock
				}
			});

			const card = container.querySelector('.card');
			await fireEvent.keyPress(card!, { key: 'a', code: 'KeyA' });

			expect(goto).not.toHaveBeenCalled();
		});

		it('should not navigate when delete button area is clicked', async () => {
			render(AnalysisCard, {
				props: {
					analysis: mockAnalysis,
					onDelete: onDeleteMock
				}
			});

			const deleteButton = screen.getByLabelText('Delete analysis');
			await fireEvent.click(deleteButton);

			expect(goto).not.toHaveBeenCalled();
		});
	});

	describe('accessibility', () => {
		it('should have role="button" on card', () => {
			const { container } = render(AnalysisCard, {
				props: {
					analysis: mockAnalysis,
					onDelete: onDeleteMock
				}
			});

			const card = container.querySelector('.card');
			expect(card).toHaveAttribute('role', 'button');
		});

		it('should have tabindex="0" on card for keyboard navigation', () => {
			const { container } = render(AnalysisCard, {
				props: {
					analysis: mockAnalysis,
					onDelete: onDeleteMock
				}
			});

			const card = container.querySelector('.card');
			expect(card).toHaveAttribute('tabindex', '0');
		});

		it('should have aria-label on delete button', () => {
			render(AnalysisCard, {
				props: {
					analysis: mockAnalysis,
					onDelete: onDeleteMock
				}
			});

			expect(screen.getByLabelText('Delete analysis')).toBeInTheDocument();
		});
	});
});
