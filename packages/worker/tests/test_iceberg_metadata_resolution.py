from unittest.mock import patch

import pytest

from runtime.exceptions import IcebergMetadataPathNotFoundError
from runtime.iceberg_metadata import resolve_iceberg_branch_metadata_path


def test_empty_listing_falls_back_to_recorded_metadata_file() -> None:
    with (
        patch("runtime.iceberg_metadata.list_metadata_files", return_value=[]),
        patch("runtime.iceberg_metadata.object_exists", return_value=True) as exists,
    ):
        resolved = resolve_iceberg_branch_metadata_path(
            "s3://bucket/clean/ds-1/master",
            "master",
            fallback_file="s3://bucket/clean/ds-1/master/metadata/00001-abc.metadata.json",
        )
    assert resolved == "s3://bucket/clean/ds-1/master/metadata/00001-abc.metadata.json"
    exists.assert_called_once_with("s3://bucket/clean/ds-1/master/metadata/00001-abc.metadata.json")


def test_empty_listing_without_fallback_raises() -> None:
    with (
        patch("runtime.iceberg_metadata.list_metadata_files", return_value=[]),
        patch("runtime.iceberg_metadata.object_exists") as exists,
    ):
        with pytest.raises(IcebergMetadataPathNotFoundError):
            resolve_iceberg_branch_metadata_path("s3://bucket/clean/ds-1/master", "master")
    exists.assert_not_called()


def test_non_empty_listing_prefers_latest_over_fallback() -> None:
    files = [
        "s3://bucket/clean/ds-1/master/metadata/00001-abc.metadata.json",
        "s3://bucket/clean/ds-1/master/metadata/00002-def.metadata.json",
    ]
    with (
        patch("runtime.iceberg_metadata.list_metadata_files", return_value=files),
        patch("runtime.iceberg_metadata.object_exists") as exists,
    ):
        resolved = resolve_iceberg_branch_metadata_path(
            "s3://bucket/clean/ds-1/master",
            "master",
            fallback_file=files[0],
        )
    assert resolved == files[-1]
    exists.assert_not_called()
