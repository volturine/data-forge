from typing import Literal

from sqlalchemy.exc import ProgrammingError

from backend_core import iceberg_catalog


class _FakeConnection:
    def __init__(self, statements: list[tuple[str, tuple[object, ...] | None]]) -> None:
        self._statements = statements

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> Literal[False]:
        return False

    def execute(self, statement: str, params: tuple[object, ...] | None = None) -> None:
        self._statements.append((statement, params))


class _FakePsycopg:
    def __init__(self, statements: list[tuple[str, tuple[object, ...] | None]], connections: list[tuple[str, bool]]) -> None:
        self._statements = statements
        self._connections = connections

    def connect(self, url: str, autocommit: bool):
        self._connections.append((url, autocommit))
        return _FakeConnection(self._statements)


def test_load_runtime_catalog_bootstraps_sql_catalog_once(monkeypatch) -> None:
    iceberg_catalog.clear_sql_catalog_bootstrap_cache()
    statements: list[tuple[str, tuple[object, ...] | None]] = []
    connections: list[tuple[str, bool]] = []
    load_calls: list[dict[str, object]] = []

    monkeypatch.setattr(iceberg_catalog, 'psycopg', _FakePsycopg(statements, connections))

    def fake_load_catalog(name: str, **config: object):
        result = {'name': name, **config}
        load_calls.append(result)
        return result

    monkeypatch.setattr(iceberg_catalog, 'load_catalog', fake_load_catalog)

    first = iceberg_catalog.load_runtime_catalog(
        'local',
        type='sql',
        uri='postgresql+psycopg://user:pass@host:5432/db',
        warehouse='file:///tmp/warehouse',
    )
    second = iceberg_catalog.load_runtime_catalog(
        'local',
        type='sql',
        uri='postgresql+psycopg://user:pass@host:5432/db',
        warehouse='file:///tmp/warehouse',
    )

    assert first == second
    assert connections == [('postgresql://user:pass@host:5432/db', True)]
    assert statements == [
        ('SELECT pg_advisory_lock(%s)', (iceberg_catalog._SQL_CATALOG_BOOTSTRAP_LOCK_KEY,)),
        ('SELECT pg_advisory_unlock(%s)', (iceberg_catalog._SQL_CATALOG_BOOTSTRAP_LOCK_KEY,)),
    ]
    assert len(load_calls) == 2

    iceberg_catalog.clear_sql_catalog_bootstrap_cache()


def test_load_runtime_catalog_retries_duplicate_bootstrap(monkeypatch) -> None:
    iceberg_catalog.clear_sql_catalog_bootstrap_cache()
    statements: list[tuple[str, tuple[object, ...] | None]] = []
    connections: list[tuple[str, bool]] = []
    attempts = 0

    monkeypatch.setattr(iceberg_catalog, 'psycopg', _FakePsycopg(statements, connections))

    def fake_load_catalog(name: str, **config: object):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ProgrammingError(
                'CREATE TABLE iceberg_tables (...)',
                {},
                Exception('relation "iceberg_tables" already exists'),
            )
        return {'name': name, **config}

    monkeypatch.setattr(iceberg_catalog, 'load_catalog', fake_load_catalog)

    catalog = iceberg_catalog.load_runtime_catalog(
        'local',
        type='sql',
        uri='postgresql+psycopg://user:pass@host:5432/db',
        warehouse='file:///tmp/warehouse',
    )

    assert catalog == {
        'name': 'local',
        'type': 'sql',
        'uri': 'postgresql+psycopg://user:pass@host:5432/db',
        'warehouse': 'file:///tmp/warehouse',
    }
    assert attempts == 2
    assert connections == [('postgresql://user:pass@host:5432/db', True)]
    assert statements == [
        ('SELECT pg_advisory_lock(%s)', (iceberg_catalog._SQL_CATALOG_BOOTSTRAP_LOCK_KEY,)),
        ('SELECT pg_advisory_unlock(%s)', (iceberg_catalog._SQL_CATALOG_BOOTSTRAP_LOCK_KEY,)),
    ]

    iceberg_catalog.clear_sql_catalog_bootstrap_cache()
