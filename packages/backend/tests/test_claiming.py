from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

from sqlmodel import Session

from backend_core.claiming import database_lease_clock


def test_postgres_lease_clock_uses_wall_time_at_write() -> None:
    session = cast(
        Session,
        SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name='postgresql'))),
    )

    clock = database_lease_clock(session, datetime(2030, 1, 1, tzinfo=UTC))

    assert str(clock.compile()) == 'clock_timestamp()'


def test_non_postgres_lease_clock_uses_database_time_fallback() -> None:
    fallback = datetime(2030, 1, 1, tzinfo=UTC)
    session = cast(
        Session,
        SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name='sqlite'))),
    )

    assert database_lease_clock(session, fallback) is fallback
