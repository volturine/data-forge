from sqlalchemy import event
from sqlmodel import Session, create_engine

from core.database import clear_engine_override, get_db, set_engine_override
from core.namespace import reset_namespace, set_namespace_context


def test_get_db_session_is_lazy_about_connection_checkout() -> None:
    engine = create_engine('sqlite:///:memory:')
    checkouts: list[object] = []

    @event.listens_for(engine, 'checkout')
    def _track_checkout(dbapi_connection, _connection_record, _connection_proxy) -> None:
        checkouts.append(dbapi_connection)

    set_engine_override(engine)
    token = set_namespace_context('default')
    session_gen = None
    session: Session | None = None
    try:
        session_gen = get_db()
        session = next(session_gen)

        assert checkouts == []

        session.connection()

        assert len(checkouts) == 1
    finally:
        if session is not None:
            session.close()
        if session_gen is not None:
            session_gen.close()
        reset_namespace(token)
        clear_engine_override()
