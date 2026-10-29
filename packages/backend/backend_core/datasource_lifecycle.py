from __future__ import annotations

from sqlmodel import Session

from backend_core.claiming import advisory_xact_lock


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
    advisory_xact_lock(session, f'dataforge:datasource-lifecycle:{namespace}:{datasource_id}', shared=shared)
