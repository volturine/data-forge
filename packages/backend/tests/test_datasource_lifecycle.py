from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from sqlmodel import Session

from backend_core.datasource_lifecycle import lock_datasource_lifecycle


class _PostgresSession:
    def __init__(self) -> None:
        self.dialect = SimpleNamespace(name='postgresql')
        self.statements: list[str] = []

    def get_bind(self):
        return self

    def execute(self, statement, _params):
        self.statements.append(str(statement))


def test_enqueue_takes_a_shared_datasource_lifecycle_lock() -> None:
    session = _PostgresSession()

    lock_datasource_lifecycle(cast(Session, session), namespace='default', datasource_id='source-1', shared=True)

    assert session.statements == ['SELECT pg_advisory_xact_lock_shared(:key)']


def test_datasource_delete_takes_an_exclusive_lifecycle_lock() -> None:
    session = _PostgresSession()

    lock_datasource_lifecycle(cast(Session, session), namespace='default', datasource_id='source-1')

    assert session.statements == ['SELECT pg_advisory_xact_lock(:key)']
