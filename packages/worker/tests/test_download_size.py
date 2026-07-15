import os
from pathlib import Path

import pytest

from runtime.compute_service import MAX_DOWNLOAD_BYTES, _ensure_download_size


def test_ensure_download_size_accepts_file_at_limit(tmp_path: Path) -> None:
    path = tmp_path / "download.parquet"
    with path.open("wb") as handle:
        handle.truncate(MAX_DOWNLOAD_BYTES)

    assert _ensure_download_size(os.fspath(path)) == MAX_DOWNLOAD_BYTES


def test_ensure_download_size_rejects_file_over_limit(tmp_path: Path) -> None:
    path = tmp_path / "download.parquet"
    with path.open("wb") as handle:
        handle.truncate(MAX_DOWNLOAD_BYTES + 1)

    with pytest.raises(ValueError, match="maximum supported download size is 10 MB"):
        _ensure_download_size(os.fspath(path))
