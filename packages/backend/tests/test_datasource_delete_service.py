import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from sqlmodel import Session, select

from backend_core import compute_requests_service, datasource_delete_service
from backend_core.domain.compute_requests.models import command_from_payload
from backend_core.domain.datasource.source_types import DataSourceType
from backend_core.persistence.compute_requests.models import ComputeRequest
from backend_core.persistence.datasource.models import DataSource
from dataforge_protocol import enums_pb2


def _preview_command(datasource_id: str):
    return command_from_payload(
        enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        {
            'analysis_id': 'analysis-1',
            'target_step_id': 'source',
            'row_limit': 100,
            'page': 1,
            'analysis_pipeline': {
                'analysis_id': 'analysis-1',
                'tabs': [
                    {
                        'id': 'tab-1',
                        'datasource': {
                            'id': datasource_id,
                            'analysis_tab_id': 'tab-1',
                            'source_type': 'file',
                            'config': {'branch': 'main'},
                        },
                        'output': {'result_id': 'result-1', 'filename': 'result.csv', 'format': 'csv'},
                        'steps': [],
                    }
                ],
            },
        },
    )


def test_finalize_delete_waits_for_active_compute_request(test_db_session, monkeypatch) -> None:
    datasource_id = str(uuid.uuid4())
    test_db_session.add(
        DataSource(
            id=datasource_id,
            name='Pending datasource',
            source_type=DataSourceType.ICEBERG.value,
            config={'metadata_path': 's3://bucket/ds'},
            is_pending_delete=True,
            created_at=datetime.now(UTC),
        )
    )
    test_db_session.commit()
    compute_requests_service.create_request(
        test_db_session,
        namespace='default',
        kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
        command=_preview_command(datasource_id),
    )
    monkeypatch.setattr(datasource_delete_service, 'reclaim_storage', lambda _snapshot: None)

    assert datasource_delete_service.finalize_delete(test_db_session, datasource_id) is False
    assert test_db_session.get(DataSource, datasource_id) is not None

    request = test_db_session.exec(select(ComputeRequest)).one()
    request.status = enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED
    test_db_session.add(request)
    test_db_session.commit()

    assert datasource_delete_service.finalize_delete(test_db_session, datasource_id) is True
    assert test_db_session.get(DataSource, datasource_id) is None


def test_active_datasource_lock_prevents_delete_before_request_enqueue(test_db_session, test_engine, monkeypatch) -> None:
    """A delete cannot finalize in the validation-to-enqueue transaction gap."""
    datasource_id = str(uuid.uuid4())
    test_db_session.add(
        DataSource(
            id=datasource_id,
            name='Racing datasource',
            source_type=DataSourceType.ICEBERG.value,
            config={'metadata_path': 's3://bucket/racing'},
            created_at=datetime.now(UTC),
        )
    )
    test_db_session.commit()
    monkeypatch.setattr(datasource_delete_service, 'reclaim_storage', lambda _snapshot: None)

    # This is the same lock held by a compute route after its active-resource
    # check. The request commit below must release it before deletion can mark
    # and finalize the row.
    datasource_delete_service.get_active_datasource(test_db_session, datasource_id, for_update=True)

    def delete_and_finalize() -> bool:
        with Session(test_engine) as delete_session:
            datasource_delete_service.request_delete(delete_session, datasource_id)
            return datasource_delete_service.finalize_delete(delete_session, datasource_id)

    with ThreadPoolExecutor(max_workers=1) as executor:
        deletion = executor.submit(delete_and_finalize)
        request = compute_requests_service.create_request(
            test_db_session,
            namespace='default',
            kind=enums_pb2.COMPUTE_REQUEST_KIND_PREVIEW,
            command=_preview_command(datasource_id),
        )
        assert deletion.result(timeout=5) is False

    stored = test_db_session.get(DataSource, datasource_id)
    assert stored is not None
    assert stored.is_pending_delete is True
    assert request.status == enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED
