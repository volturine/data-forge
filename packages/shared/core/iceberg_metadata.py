import os
from pathlib import Path
from urllib.parse import unquote, urlparse

import pyarrow as pa  # type: ignore[import-untyped]
from pyiceberg.table import Table as IcebergTable

from core.namespace import namespace_paths


class IcebergMetadataPathNotFoundError(ValueError):
    def __init__(self, metadata_path: str):
        self.metadata_path = metadata_path
        super().__init__(f'Iceberg metadata_path not found: {metadata_path}')


def sync_iceberg_schema(table: IcebergTable, new_schema: pa.Schema) -> bool:
    current = table.schema()
    current_names = {field.name for field in current.fields}
    new_names = set(new_schema.names)

    to_delete = current_names - new_names
    has_additions = bool(new_names - current_names)

    if not to_delete and not has_additions:
        return False

    update = table.update_schema()
    for name in sorted(to_delete):
        update.delete_column(name)
    if has_additions:
        update.union_by_name(new_schema)
    update.commit()
    return True


def resolve_iceberg_metadata_path(metadata_path: str, *, namespace_name: str | None = None, data_root: str | Path | None = None) -> str:
    normalized = _strip_file_scheme(metadata_path)
    path = Path(normalized)
    resolved = path.resolve()
    root = _resolve_iceberg_data_root(namespace_name=namespace_name, data_root=data_root)
    if root not in resolved.parents and root != resolved:
        raise ValueError('Iceberg metadata_path must be inside data directory')
    if path.suffix == '.db':
        raise ValueError('Iceberg metadata_path must point to metadata.json, not catalog.db')
    if path.is_file():
        if path.name.endswith('.metadata.json'):
            return str(path)
        raise ValueError('Iceberg metadata_path must be a table directory or metadata.json')
    if not path.exists():
        raise IcebergMetadataPathNotFoundError(metadata_path)
    if not path.is_dir():
        raise ValueError(f'Iceberg metadata_path must be a file or directory: {metadata_path}')
    if path.name == 'metadata':
        return _latest_metadata_file(path)
    metadata_dir = path / 'metadata'
    if metadata_dir.is_dir():
        return _latest_metadata_file(metadata_dir)
    raise ValueError('Iceberg metadata_path must be a table directory containing metadata/')


def resolve_iceberg_branch_metadata_path(
    metadata_path: str, branch: str | None, *, namespace_name: str | None = None, data_root: str | Path | None = None
) -> str:
    normalized = _strip_file_scheme(metadata_path)
    path = Path(normalized)
    if path.suffix == '.metadata.json' or path.name == 'metadata' or path.is_file():
        return resolve_iceberg_metadata_path(metadata_path, namespace_name=namespace_name, data_root=data_root)
    if branch:
        branch_path = path / branch
        if branch_path.exists():
            return resolve_iceberg_metadata_path(str(branch_path), namespace_name=namespace_name, data_root=data_root)
    metadata_dir = path / 'metadata'
    if metadata_dir.is_dir():
        return resolve_iceberg_metadata_path(str(metadata_dir), namespace_name=namespace_name, data_root=data_root)
    if path.is_dir():
        children = [entry for entry in path.iterdir() if entry.is_dir()]
        if len(children) == 1:
            return resolve_iceberg_metadata_path(str(children[0]), namespace_name=namespace_name, data_root=data_root)
    return resolve_iceberg_metadata_path(metadata_path, namespace_name=namespace_name, data_root=data_root)


def _resolve_iceberg_data_root(*, namespace_name: str | None = None, data_root: str | Path | None = None) -> Path:
    if data_root is not None:
        return Path(os.path.realpath(Path(data_root).resolve()))
    return Path(os.path.realpath(namespace_paths(namespace_name).base_dir.resolve()))


def _latest_metadata_file(metadata_dir: Path) -> str:
    files = sorted(metadata_dir.glob('*.metadata.json'))
    if not files:
        raise ValueError(f'No metadata.json files found in {metadata_dir}')
    return str(files[-1])


def _strip_file_scheme(metadata_path: str) -> str:
    parsed = urlparse(metadata_path)
    if parsed.scheme != 'file':
        return metadata_path
    return unquote(parsed.path)
