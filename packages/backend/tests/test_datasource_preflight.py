import pytest

from modules.datasource.preflight import _string_list, format_excel_cell_range, preview_rows


def test_preflight_result_converts_worker_rows_and_metadata() -> None:
    result: dict[str, object] = {
        'preview_rows': [{'cells': ['id', 'name']}, {'cells': ['1', 'Ada']}],
    }

    assert preview_rows(result) == [['id', 'name'], ['1', 'Ada']]
    assert _string_list(['Sheet1', 'Sheet2']) == ['Sheet1', 'Sheet2']


def test_preflight_result_rejects_invalid_metadata() -> None:
    with pytest.raises(ValueError, match='list of names'):
        _string_list(['Sheet1', 2])


def test_format_excel_cell_range_handles_multi_letter_columns() -> None:
    assert format_excel_cell_range('Data', 0, 25, 9, 26) == 'Data!Z1:AA10'
