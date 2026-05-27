from __future__ import annotations

import logging
from typing import Any

from contracts.datasource.models import DataSource
from contracts.datasource.source_types import DataSourceType
from core.exceptions import FileError
from core.iceberg_catalog import load_runtime_catalog
from core.object_store import delete_object, delete_prefix, is_managed_object_store_url, object_store_storage_options

logger = logging.getLogger(__name__)


class DatasourceStorageCleanup:
    def delete(self, datasource: DataSource) -> None:
        if datasource.source_type_kind() == DataSourceType.FILE and isinstance(datasource.config, dict):
            self._delete_managed_object(datasource.config.get('file_path'))
        if not datasource.is_iceberg or not isinstance(datasource.config, dict):
            return
        config = datasource.config
        self._drop_iceberg_catalog_table(config)
        self._delete_managed_prefix(config.get('metadata_path'))
        source = config.get('source')
        if not isinstance(source, dict):
            return
        if source.get('source_type') != DataSourceType.FILE:
            return
        self._delete_managed_object(source.get('file_path'))

    @staticmethod
    def _delete_managed_prefix(prefix: object) -> None:
        if not isinstance(prefix, str) or not is_managed_object_store_url(prefix):
            return
        try:
            delete_prefix(prefix)
            logger.info('Deleted Iceberg object prefix: %s', prefix)
        except Exception as exc:
            logger.error('Object storage error when deleting Iceberg prefix %s: %s', prefix, exc)
            raise FileError(
                f'Failed to delete Iceberg object prefix: {prefix}',
                error_code='FILE_DELETE_ERROR',
                details={'path': prefix, 'error': str(exc)},
            ) from exc

    @staticmethod
    def _delete_managed_object(file_path: object) -> None:
        if not isinstance(file_path, str) or not is_managed_object_store_url(file_path):
            return
        try:
            delete_object(file_path)
            logger.info('Deleted object: %s', file_path)
        except Exception as exc:
            logger.error('Object storage error when deleting file %s: %s', file_path, exc)
            raise FileError(
                f'Failed to delete object: {file_path}',
                error_code='FILE_DELETE_ERROR',
                details={'file_path': file_path, 'error': str(exc)},
            ) from exc

    @staticmethod
    def _drop_iceberg_catalog_table(config: dict[str, Any]) -> None:
        catalog_type = config.get('catalog_type')
        catalog_uri = config.get('catalog_uri')
        warehouse = config.get('warehouse')
        namespace = config.get('namespace')
        table = config.get('table')
        if not all(isinstance(value, str) and value for value in [catalog_type, catalog_uri, warehouse, namespace, table]):
            return
        catalog = load_runtime_catalog(
            'local',
            type=catalog_type,
            uri=catalog_uri,
            warehouse=warehouse,
            **object_store_storage_options(),
        )
        identifier = f'{namespace}.{table}'
        if catalog.table_exists(identifier):
            catalog.drop_table(identifier)
            logger.info('Deleted Iceberg catalog table: %s', identifier)


_STORAGE_CLEANUP = DatasourceStorageCleanup()


def cleanup_datasource_storage(datasource: DataSource) -> None:
    _STORAGE_CLEANUP.delete(datasource)
