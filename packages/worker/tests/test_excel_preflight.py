from contextlib import contextmanager
from pathlib import Path

from datasources import excel_preflight


def test_preflight_actions_preview_once_and_keep_their_response_shapes(monkeypatch) -> None:
    preview_calls: list[str] = []

    @contextmanager
    def local_workbook(_source_path: str):
        yield Path("workbook.xlsx")

    def read_metadata(_path: Path):
        return ["Sheet1"], {"Sheet1": ["Table1"]}, ["Named1"]

    def preview(_path: Path, **kwargs: object) -> dict[str, object]:
        preview_calls.append(str(kwargs["sheet_name"]))
        return {
            "preflight_id": "",
            "preview_rows": [],
            "sheet_name": kwargs["sheet_name"],
            "start_row": 0,
            "start_col": 0,
            "end_col": 1,
            "detected_end_row": 0,
        }

    monkeypatch.setattr(excel_preflight, "_local_workbook", local_workbook)
    monkeypatch.setattr(excel_preflight, "_read_metadata", read_metadata)
    monkeypatch.setattr(excel_preflight, "_preview", preview)

    common = {
        "preflight_id": "preflight-1",
        "source_path": "upload.xlsx",
        "delete_source": False,
        "sheet_name": None,
        "start_row": 0,
        "start_col": 0,
        "end_col": 1,
        "end_row": None,
        "table_name": None,
        "named_range": None,
        "cell_range": None,
    }

    initial = excel_preflight.execute_preflight(action="initial", **common)
    assert preview_calls == ["Sheet1"]
    preview_calls.clear()
    preview = excel_preflight.execute_preflight(action="preview", **common)
    assert preview_calls == [""]
    preview_calls.clear()
    selection = excel_preflight.execute_preflight(action="resolve_selection", **common)

    assert preview_calls == [""]
    assert initial["preflight_id"] == "preflight-1"
    assert initial["sheets"] == ["Sheet1"]
    assert initial["tables"] == {"Sheet1": {"columns": ["Table1"]}}
    assert initial["named_ranges"] == ["Named1"]
    assert preview == {
        "preflight_id": "preflight-1",
        "preview_rows": [],
        "sheet_name": "",
        "start_row": 0,
        "start_col": 0,
        "end_col": 1,
        "detected_end_row": 0,
    }
    assert selection == {
        "preflight_id": "preflight-1",
        "sheet_name": "",
        "start_row": 0,
        "start_col": 0,
        "end_col": 1,
        "detected_end_row": 0,
    }
