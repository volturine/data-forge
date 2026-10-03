from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from runtime.iceberg_catalog import ensure_catalog_namespace


def _integrity_error(*, sqlstate: str, table: str, constraint: str) -> IntegrityError:
    original = SimpleNamespace(
        sqlstate=sqlstate,
        diag=SimpleNamespace(table_name=table, constraint_name=constraint),
    )
    return IntegrityError("INSERT INTO iceberg_namespace_properties", {}, original)


def test_namespace_creation_accepts_only_the_concurrent_create_loser() -> None:
    class Catalog:
        create_calls = 0
        exists_calls = 0

        def create_namespace_if_not_exists(self, namespace: str) -> None:
            self.create_calls += 1
            assert namespace == "outputs"
            raise _integrity_error(
                sqlstate="23505",
                table="iceberg_namespace_properties",
                constraint="iceberg_namespace_properties_pkey",
            )

        def namespace_exists(self, namespace: str) -> bool:
            self.exists_calls += 1
            assert namespace == "outputs"
            return True

    catalog = Catalog()

    ensure_catalog_namespace(catalog, "outputs")

    assert catalog.create_calls == 1
    assert catalog.exists_calls == 1


@pytest.mark.parametrize(
    ("sqlstate", "table", "constraint"),
    [
        ("23505", "iceberg_tables", "iceberg_tables_pkey"),
        ("23502", "iceberg_namespace_properties", "iceberg_namespace_properties_pkey"),
    ],
)
def test_namespace_creation_propagates_unrelated_integrity_errors(
    sqlstate: str,
    table: str,
    constraint: str,
) -> None:
    class Catalog:
        def create_namespace_if_not_exists(self, _namespace: str) -> None:
            raise _integrity_error(sqlstate=sqlstate, table=table, constraint=constraint)

        def namespace_exists(self, _namespace: str) -> bool:
            pytest.fail("Unrelated integrity errors must not be treated as a create race")

    with pytest.raises(IntegrityError):
        ensure_catalog_namespace(Catalog(), "outputs")


def test_namespace_creation_propagates_duplicate_when_namespace_is_still_missing() -> None:
    class Catalog:
        def create_namespace_if_not_exists(self, _namespace: str) -> None:
            raise _integrity_error(
                sqlstate="23505",
                table="iceberg_namespace_properties",
                constraint="iceberg_namespace_properties_pkey",
            )

        def namespace_exists(self, _namespace: str) -> bool:
            return False

    with pytest.raises(IntegrityError):
        ensure_catalog_namespace(Catalog(), "outputs")
