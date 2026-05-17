import { describe, test, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/svelte';
import { createRawSnippet } from 'svelte';
import SearchableDropdown from './SearchableDropdown.svelte';

const options = [
	{ id: 'a', label: 'Alpha' },
	{ id: 'b', label: 'Beta' },
	{ id: 'c', label: 'Charlie' }
];

const renderOption = createRawSnippet(
	(
		payload: () => {
			option: { id: string; label: string };
			selected: boolean;
			onSelect: () => void;
		}
	) => ({
		render: () => {
			const p = payload();
			return `<div role="option" aria-selected="${p.selected}" data-option-id="${p.option.id}">${p.option.label}</div>`;
		},
		setup: (node: Element) => {
			node.addEventListener('click', () => payload().onSelect());
		}
	})
);

function renderDropdown(props: Record<string, unknown> = {}) {
	return render(SearchableDropdown, {
		props: {
			options,
			value: '',
			onChange: vi.fn(),
			renderOption,
			...props
		}
	});
}

describe('SearchableDropdown', () => {
	beforeEach(() => {
		document.body.style.overflow = '';
	});

	describe('trigger', () => {
		test('renders trigger button with placeholder', () => {
			renderDropdown();
			const trigger = screen.getByRole('button');
			expect(trigger).toHaveTextContent('Select...');
		});

		test('renders custom placeholder', () => {
			renderDropdown({ placeholder: 'Pick one' });
			expect(screen.getByRole('button')).toHaveTextContent('Pick one');
		});

		test('shows selected option label in single mode', () => {
			renderDropdown({ value: 'b' });
			expect(screen.getByRole('button')).toHaveTextContent('Beta');
		});

		test('shows count in multi mode', () => {
			renderDropdown({ mode: 'multi', value: ['a', 'c'] });
			expect(screen.getByRole('button')).toHaveTextContent('2 selected');
		});

		test('disabled trigger cannot be clicked', () => {
			renderDropdown({ disabled: true });
			const trigger = screen.getByRole('button');
			expect(trigger).toBeDisabled();
		});
	});

	describe('menu open/close', () => {
		test('menu is closed by default', () => {
			renderDropdown();
			expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
		});

		test('opens menu on trigger click', async () => {
			renderDropdown();
			await fireEvent.click(screen.getByRole('button'));
			expect(screen.getByRole('listbox')).toBeInTheDocument();
		});

		test('sets aria-expanded on trigger when open', async () => {
			renderDropdown();
			const trigger = screen.getByRole('button');
			expect(trigger).toHaveAttribute('aria-expanded', 'false');
			await fireEvent.click(trigger);
			expect(trigger).toHaveAttribute('aria-expanded', 'true');
		});
	});

	describe('options rendering', () => {
		test('renders all options when opened', async () => {
			renderDropdown();
			await fireEvent.click(screen.getByRole('button'));
			const listbox = screen.getByRole('listbox');
			const rendered = within(listbox).getAllByRole('option');
			expect(rendered).toHaveLength(3);
			expect(rendered[0]).toHaveTextContent('Alpha');
			expect(rendered[1]).toHaveTextContent('Beta');
			expect(rendered[2]).toHaveTextContent('Charlie');
		});

		test('shows empty label when no options match search', async () => {
			renderDropdown({ searchDelay: 0 });
			await fireEvent.click(screen.getByRole('button'));
			const searchInput = screen.getByLabelText('Search');
			await fireEvent.input(searchInput, { target: { value: 'zzz' } });
			await vi.waitFor(() => {
				expect(screen.getByText('No results')).toBeInTheDocument();
			});
		});

		test('custom empty label', async () => {
			renderDropdown({ emptyLabel: 'Nothing found', searchDelay: 0 });
			await fireEvent.click(screen.getByRole('button'));
			const searchInput = screen.getByLabelText('Search');
			await fireEvent.input(searchInput, { target: { value: 'zzz' } });
			await vi.waitFor(() => {
				expect(screen.getByText('Nothing found')).toBeInTheDocument();
			});
		});
	});

	describe('single mode selection', () => {
		test('calls onChange with selected id', async () => {
			const onChange = vi.fn();
			renderDropdown({ onChange });
			await fireEvent.click(screen.getByRole('button'));
			const option = screen.getByText('Beta');
			await fireEvent.click(option);
			expect(onChange).toHaveBeenCalledWith('b');
		});

		test('closes menu after selection in single mode', async () => {
			const onChange = vi.fn();
			renderDropdown({ onChange });
			await fireEvent.click(screen.getByRole('button'));
			expect(screen.getByRole('listbox')).toBeInTheDocument();
			await fireEvent.click(screen.getByText('Alpha'));
			expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
		});
	});

	describe('multi mode', () => {
		test('sets aria-multiselectable on listbox', async () => {
			renderDropdown({ mode: 'multi', value: [] });
			await fireEvent.click(screen.getByRole('button'));
			expect(screen.getByRole('listbox')).toHaveAttribute('aria-multiselectable', 'true');
		});

		test('shows Done button in multi mode', async () => {
			renderDropdown({ mode: 'multi', value: [] });
			await fireEvent.click(screen.getByRole('button'));
			expect(screen.getByText('Done')).toBeInTheDocument();
		});

		test('Done button shows count when items selected', async () => {
			renderDropdown({ mode: 'multi', value: ['a', 'c'] });
			await fireEvent.click(screen.getByRole('button'));
			expect(screen.getByText('Done (2)')).toBeInTheDocument();
		});
	});

	describe('select all / clear (multi mode)', () => {
		test('shows select all and clear buttons when enabled', async () => {
			renderDropdown({ mode: 'multi', value: [], showSelectAll: true });
			await fireEvent.click(screen.getByRole('button'));
			expect(screen.getByText(/Select All/)).toBeInTheDocument();
			expect(screen.getByText('Clear')).toBeInTheDocument();
		});

		test('does not show select all by default', async () => {
			renderDropdown({ mode: 'multi', value: [] });
			await fireEvent.click(screen.getByRole('button'));
			expect(screen.queryByText(/Select All/)).not.toBeInTheDocument();
		});
	});

	describe('clearable', () => {
		test('shows clear button when clearable and value selected', () => {
			renderDropdown({ clearable: true, value: 'a' });
			expect(screen.getByLabelText('Clear selection')).toBeInTheDocument();
		});

		test('does not show clear button when no value', () => {
			renderDropdown({ clearable: true, value: '' });
			expect(screen.queryByLabelText('Clear selection')).not.toBeInTheDocument();
		});

		test('calls onChange with empty string on clear in single mode', async () => {
			const onChange = vi.fn();
			renderDropdown({ clearable: true, value: 'a', onChange });
			await fireEvent.click(screen.getByLabelText('Clear selection'));
			expect(onChange).toHaveBeenCalledWith('');
		});

		test('calls onChange with empty array on clear in multi mode', async () => {
			const onChange = vi.fn();
			renderDropdown({ clearable: true, value: ['a'], mode: 'multi', onChange });
			await fireEvent.click(screen.getByLabelText('Clear selection'));
			expect(onChange).toHaveBeenCalledWith([]);
		});
	});

	describe('listAriaLabel', () => {
		test('sets custom aria-label on listbox', async () => {
			renderDropdown({ listAriaLabel: 'Column list' });
			await fireEvent.click(screen.getByRole('button'));
			expect(screen.getByRole('listbox')).toHaveAttribute('aria-label', 'Column list');
		});
	});

	describe('input trigger type', () => {
		test('renders input trigger when triggerType is input', () => {
			renderDropdown({ triggerType: 'input' });
			expect(screen.getByLabelText('Search')).toBeInTheDocument();
			expect(screen.queryByRole('button')).not.toBeInTheDocument();
		});

		test('opens menu on input focus', async () => {
			renderDropdown({ triggerType: 'input' });
			await fireEvent.focus(screen.getByLabelText('Search'));
			expect(screen.getByRole('listbox')).toBeInTheDocument();
		});
	});

	describe('selected list display', () => {
		test('shows selected items when showSelectedList is true', () => {
			renderDropdown({ mode: 'multi', value: ['a', 'c'], showSelectedList: true });
			expect(screen.getByText('a, c')).toBeInTheDocument();
		});

		test('does not show selected list when showSelectedList is false', () => {
			renderDropdown({ mode: 'multi', value: ['a', 'c'], showSelectedList: false });
			expect(screen.queryByText('a, c')).not.toBeInTheDocument();
		});
	});
});
