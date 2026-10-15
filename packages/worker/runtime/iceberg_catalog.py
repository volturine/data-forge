from __future__ import annotations

import logging
import threading
from typing import Any

import psycopg
from pyiceberg.catalog import load_catalog
from sqlalchemy.exc import IntegrityError, ProgrammingError

logger = logging.getLogger(__name__)

_SQL_CATALOG_BOOTSTRAP_LOCK_KEY = 4815162343
_sql_catalog_bootstrapped_uris: set[str] = set()
_sql_catalog_bootstrapped_uris_guard = threading.Lock()


def _is_concurrent_namespace_create(error: IntegrityError) -> bool:
    original = error.orig
    diagnostic = getattr(original, "diag", None)
    return (
        getattr(original, "sqlstate", None) == "23505"
        and getattr(diagnostic, "table_name", None) == "iceberg_namespace_properties"
        and getattr(diagnostic, "constraint_name", None) == "iceberg_namespace_properties_pkey"
    )


def ensure_catalog_namespace(catalog: Any, namespace: str) -> None:
    try:
        catalog.create_namespace_if_not_exists(namespace)
    except IntegrityError as exc:
        if not _is_concurrent_namespace_create(exc) or not catalog.namespace_exists(namespace):
            raise
        logger.info("Namespace %s was created concurrently; continuing", namespace)


def load_runtime_catalog(name: str, **catalog_config: Any):
    catalog_type = catalog_config.get("type")
    catalog_uri = catalog_config.get("uri")
    if catalog_type != "sql" or not isinstance(catalog_uri, str) or not catalog_uri:
        return load_catalog(name, **catalog_config)

    with _sql_catalog_bootstrapped_uris_guard:
        if catalog_uri in _sql_catalog_bootstrapped_uris:
            return load_catalog(name, **catalog_config)

        lock_url = catalog_uri.replace("postgresql+psycopg://", "postgresql://", 1) if catalog_uri.startswith("postgresql+psycopg://") else catalog_uri
        with psycopg.connect(lock_url, autocommit=True) as connection:
            connection.execute("SELECT pg_advisory_lock(%s)", (_SQL_CATALOG_BOOTSTRAP_LOCK_KEY,))
            try:
                try:
                    catalog = load_catalog(name, **catalog_config)
                except ProgrammingError as exc:
                    if 'relation "iceberg_tables" already exists' not in str(exc):
                        raise
                    logger.info("Iceberg SQL catalog bootstrap raced; retrying after duplicate-table error")
                    catalog = load_catalog(name, **catalog_config)
            finally:
                connection.execute("SELECT pg_advisory_unlock(%s)", (_SQL_CATALOG_BOOTSTRAP_LOCK_KEY,))

        _sql_catalog_bootstrapped_uris.add(catalog_uri)
        return catalog
