from __future__ import annotations

import logging
import threading
from typing import Any

import psycopg
from pyiceberg.catalog import load_catalog
from sqlalchemy.exc import ProgrammingError

logger = logging.getLogger(__name__)

_SQL_CATALOG_BOOTSTRAP_LOCK_KEY = 4815162343
_sql_catalog_bootstrapped_uris: set[str] = set()
_sql_catalog_bootstrapped_uris_guard = threading.Lock()


def _normalized_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql+psycopg://"):
        return database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    return database_url


def _is_sql_catalog_bootstrap_duplicate(error: ProgrammingError) -> bool:
    return 'relation "iceberg_tables" already exists' in str(error)


def load_runtime_catalog(name: str, **catalog_config: Any):
    catalog_type = catalog_config.get("type")
    catalog_uri = catalog_config.get("uri")
    if catalog_type != "sql" or not isinstance(catalog_uri, str) or not catalog_uri:
        return load_catalog(name, **catalog_config)

    with _sql_catalog_bootstrapped_uris_guard:
        if catalog_uri in _sql_catalog_bootstrapped_uris:
            return load_catalog(name, **catalog_config)

        with psycopg.connect(_normalized_database_url(catalog_uri), autocommit=True) as connection:
            connection.execute("SELECT pg_advisory_lock(%s)", (_SQL_CATALOG_BOOTSTRAP_LOCK_KEY,))
            try:
                try:
                    catalog = load_catalog(name, **catalog_config)
                except ProgrammingError as exc:
                    if not _is_sql_catalog_bootstrap_duplicate(exc):
                        raise
                    logger.info("Iceberg SQL catalog bootstrap raced; retrying after duplicate-table error")
                    catalog = load_catalog(name, **catalog_config)
            finally:
                connection.execute("SELECT pg_advisory_unlock(%s)", (_SQL_CATALOG_BOOTSTRAP_LOCK_KEY,))

        _sql_catalog_bootstrapped_uris.add(catalog_uri)
        return catalog
