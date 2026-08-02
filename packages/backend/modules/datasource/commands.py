from dataclasses import dataclass
from datetime import UTC, datetime

from sqlmodel import Session

from backend_core import build_jobs_service, build_runs_service, runtime_outbox_service
from backend_core.domain.datasource.models import DataSourceCreatedBy
from backend_core.persistence.datasource.models import DataSource
from backend_core.transactions import committed


class OutputPublicationClaimLost(RuntimeError):
    pass


@dataclass(frozen=True)
class OutputPublicationClaim:
    job_id: str
    build_id: str
    worker_id: str
    claim_token: str
    lease_generation: int
    build_result: dict[str, object]


def stage_output_datasource(
    session: Session,
    *,
    result_id: str,
    name: str,
    source_type: str,
    config: dict[str, object],
    schema_cache: dict[str, object],
    keep_schema_cache: bool,
    analysis_id: str | None,
    is_hidden: bool | None,
    claim: OutputPublicationClaim | None,
    notification_deliveries: list[dict[str, object]],
) -> DataSource:
    if claim is not None:
        active_claim = build_jobs_service.lock_active_job_claim(
            session,
            claim.job_id,
            build_id=claim.build_id,
            worker_id=claim.worker_id,
            claim_token=claim.claim_token,
            lease_generation=claim.lease_generation,
        )
        if active_claim is None:
            raise OutputPublicationClaimLost('Build job lease is no longer active')

    datasource = session.get(DataSource, result_id)
    if datasource is None:
        datasource = DataSource(
            id=result_id,
            name=name,
            source_type=source_type,
            config=config,
            schema_cache=schema_cache,
            created_by_analysis_id=analysis_id,
            created_by=DataSourceCreatedBy.ANALYSIS.value,
            is_hidden=is_hidden if is_hidden is not None else True,
            created_at=datetime.now(UTC),
        )
    else:
        datasource.name = name
        datasource.source_type = source_type
        datasource.config = config
        if not keep_schema_cache:
            datasource.schema_cache = schema_cache
        datasource.created_by_analysis_id = analysis_id
        datasource.created_by = DataSourceCreatedBy.ANALYSIS.value
        if is_hidden is not None:
            datasource.is_hidden = is_hidden
    session.add(datasource)

    if claim is not None:
        build_runs_service.stage_build_result_json(session, claim.build_id, claim.build_result)
    for delivery in notification_deliveries:
        runtime_outbox_service.enqueue_notification_delivery(session, delivery)
    return datasource


upsert_output_datasource = committed(stage_output_datasource, refresh=True)
