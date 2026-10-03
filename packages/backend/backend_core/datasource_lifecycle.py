from __future__ import annotations

from hashlib import sha256

from sqlalchemy import text
from sqlmodel import Session


def _datasource_lock_key(namespace: str, datasource_id: str) -> int:
    digest = sha256(f'dataforge:datasource-lifecycle:{namespace}:{datasource_id}'.encode()).digest()
    return int.from_bytes(digest[:8], byteorder='big', signed=True)


def uses_postgres_advisory_locks(session: Session) -> bool:
    get_bind = getattr(session, 'get_bind', None)
    if not callable(get_bind):
        return False
    bind = get_bind()
    return getattr(getattr(bind, 'dialect', None), 'name', None) == 'postgresql'


def lock_datasource_lifecycle(
    session: Session,
    *,
    namespace: str,
    datasource_id: str,
    shared: bool = False,
) -> None:
    """Fence enqueue readers against datasource tombstone and final deletion.

    Enqueue validation takes a shared transaction lock so independent previews
    using one source remain concurrent. Tombstone and final-delete operations
    take the exclusive form and therefore wait for in-flight enqueues before
    changing datasource state.
    """
    if not uses_postgres_advisory_locks(session):
        return
    lock_function = 'pg_advisory_xact_lock_shared' if shared else 'pg_advisory_xact_lock'
    session.execute(
        text(f'SELECT {lock_function}(:key)'),
        {'key': _datasource_lock_key(namespace, datasource_id)},
    )
