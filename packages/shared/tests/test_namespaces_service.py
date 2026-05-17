from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError

from contracts.namespaces.models import RuntimeNamespace
from core import namespaces_service


class _RacingNamespaceSession:
    def __init__(self) -> None:
        self._existing: RuntimeNamespace | None = None
        self._commits = 0
        self.added: list[RuntimeNamespace] = []
        self.rolled_back = False
        self.refreshed: list[RuntimeNamespace] = []

    def get(self, model: type[RuntimeNamespace], name: str) -> RuntimeNamespace | None:
        assert model is RuntimeNamespace
        if self._commits == 0:
            return None
        if self._existing is None:
            self._existing = RuntimeNamespace(
                name=name,
                created_at=datetime.now(UTC).replace(tzinfo=None),
                updated_at=datetime.now(UTC).replace(tzinfo=None),
            )
        return self._existing

    def add(self, record: RuntimeNamespace) -> None:
        self.added.append(record)

    def commit(self) -> None:
        self._commits += 1
        if self._commits == 1:
            raise IntegrityError('insert into runtime_namespaces', {'name': 'alpha'}, Exception('duplicate'))

    def rollback(self) -> None:
        self.rolled_back = True

    def refresh(self, record: RuntimeNamespace) -> None:
        self.refreshed.append(record)


def test_register_namespace_recovers_from_concurrent_insert() -> None:
    session = _RacingNamespaceSession()

    record = namespaces_service.register_namespace(session, 'alpha')  # type: ignore[arg-type]

    assert session.rolled_back is True
    assert record.name == 'alpha'
    assert session.refreshed[-1] is record
