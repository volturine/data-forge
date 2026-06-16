from __future__ import annotations

from pathlib import Path

from backend_core.config import settings
from backend_core.data_plane_client import client_from_settings


def object_store_storage_options() -> dict[str, object]:
    return {
        's3.endpoint': settings.object_store_endpoint,
        's3.access-key-id': settings.object_store_access_key,
        's3.secret-access-key': settings.object_store_secret_key,
        's3.region': settings.object_store_region,
        's3.force-virtual-addressing': False,
        'py-io-impl': 'pyiceberg.io.pyarrow.PyArrowFileIO',
    }


def upload_file(local_path: Path, target_url: str) -> str:
    return upload_bytes(local_path.read_bytes(), target_url)


def upload_bytes(data: bytes, target_url: str, *, content_type: str | None = None) -> str:
    return client_from_settings().upload_bytes(data, target_url, content_type=content_type)


def download_file(source_url: str, target_path: Path) -> Path:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(download_bytes(source_url))
    return target_path


def download_bytes(source_url: str) -> bytes:
    return client_from_settings().download_bytes(source_url)


def object_exists(source_url: str) -> bool:
    return client_from_settings().object_exists(source_url)


def delete_object(source_url: str) -> None:
    client_from_settings().delete_object(source_url)


def list_prefixes(prefix_url: str) -> list[str]:
    return client_from_settings().list_prefixes(prefix_url)


def list_metadata_files(base_url: str) -> list[str]:
    return client_from_settings().list_metadata_files(base_url)


def delete_prefix(prefix_url: str) -> None:
    client_from_settings().delete_prefix(prefix_url)
