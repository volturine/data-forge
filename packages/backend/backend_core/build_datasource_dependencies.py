from __future__ import annotations

from sqlmodel import Session

from backend_core import datasource_delete_service
from backend_core.datasource_lifecycle import lock_datasource_lifecycle, uses_postgres_advisory_locks
from backend_core.domain.compute.schemas import AnalysisPipelinePayload


def external_datasource_ids(pipeline: AnalysisPipelinePayload) -> tuple[str, ...]:
    """Return the exact datasource RIDs a queued pipeline can read."""
    tab_ids = {tab.id for tab in pipeline.tabs}
    output_ids = {result_id for tab in pipeline.tabs if isinstance((result_id := tab.output.get('result_id')), str)}
    local_ids = tab_ids | output_ids
    external_ids: set[str] = set()

    for tab in pipeline.tabs:
        datasource = tab.datasource
        # Scheduled-ingest pipelines intentionally use the source RID as their
        # output RID; it remains an external read despite that local ID overlap.
        if datasource.analysis_tab_id is None and (datasource.id not in local_ids or datasource.source_type == 'schedule'):
            external_ids.add(datasource.id)
        for step in tab.steps:
            config = step.get('config')
            if not isinstance(config, dict):
                continue
            right_source = config.get('right_source')
            if isinstance(right_source, str) and right_source not in local_ids:
                external_ids.add(right_source)
            sources = config.get('sources')
            if isinstance(sources, list):
                external_ids.update(source for source in sources if isinstance(source, str) and source not in local_ids)

    return tuple(sorted(external_ids))


def lock_active_datasources(session: Session, *, namespace: str, datasource_ids: tuple[str, ...]) -> None:
    """Fence a durable reader enqueue against datasource tombstone/finalization."""
    for datasource_id in sorted(set(datasource_ids)):
        lock_datasource_lifecycle(session, namespace=namespace, datasource_id=datasource_id, shared=True)
        datasource_delete_service.get_active_datasource(
            session,
            datasource_id,
            for_update=not uses_postgres_advisory_locks(session),
        )
