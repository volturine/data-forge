from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

from sqlmodel import Session

from backend_core import compute_requests_service
from backend_core.domain.compute_requests.models import command_from_payload
from backend_core.persistence.datasource.models import DataSource
from dataforge_protocol import enums_pb2
from modules.compute import executor_client


def test_durable_command_preserves_source_revision_and_revision_changes_split_flights(test_db_session: Session) -> None:
    datasource_id = str(uuid4())
    source = DataSource(
        id=datasource_id,
        name='Revision source',
        source_type='file',
        config={'file_path': 's3://default/uploads/old.csv'},
        revision=1,
        created_at=datetime.now(UTC),
    )
    test_db_session.add(source)
    test_db_session.commit()
    command = command_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA, {'datasource_id': datasource_id})
    first, created = compute_requests_service.stage_shared_flight_request(
        test_db_session, namespace='default', kind=enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA, command=command
    )
    test_db_session.commit()
    assert created
    source.revision = 2
    source.config = {'file_path': 's3://default/uploads/new.csv'}
    test_db_session.add(source)
    test_db_session.commit()
    second, created = compute_requests_service.stage_shared_flight_request(
        test_db_session, namespace='default', kind=enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_SCHEMA, command=command
    )
    test_db_session.commit()
    first_command = compute_requests_service.command_envelope_for_request(first).command
    second_command = compute_requests_service.command_envelope_for_request(second).command
    assert first.id != second.id
    assert first_command.input_revisions[0].revision == 1
    assert second_command.input_revisions[0].revision == 2
    assert compute_requests_service._flight_key(cast(enums_pb2.ComputeRequestKind, first.kind), first_command) != compute_requests_service._flight_key(
        cast(enums_pb2.ComputeRequestKind, second.kind), second_command
    )
    assert first.engine_resource_id == second.engine_resource_id == datasource_id


def test_create_request_preallocates_its_exact_datasource_worker_rid(test_db_session: Session) -> None:
    command = command_from_payload(
        enums_pb2.COMPUTE_REQUEST_KIND_CREATE_DATABASE_DATASOURCE,
        {'name': 'Created', 'connection_string': 'postgresql://source-db/data', 'query': 'SELECT 1', 'branch': 'master'},
    )
    request = compute_requests_service.create_request(
        test_db_session, namespace='default', kind=enums_pb2.COMPUTE_REQUEST_KIND_CREATE_DATABASE_DATASOURCE, command=command
    )
    assert request.engine_resource_id == request.id
    assert request.engine_scope == enums_pb2.COMPUTE_WORKER_SCOPE_DATASOURCE_PREVIEW
    assert request.engine_reuse_policy == enums_pb2.COMPUTE_WORKER_REUSE_POLICY_SHARED


def test_preflight_initial_and_preview_jobs_share_only_the_stable_draft_rid(test_db_session: Session) -> None:
    preflight_id = str(uuid4())
    requests = []
    for action in (enums_pb2.DATASOURCE_PREFLIGHT_ACTION_INITIAL, enums_pb2.DATASOURCE_PREFLIGHT_ACTION_PREVIEW):
        command = command_from_payload(
            enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_PREFLIGHT,
            {'preflight_id': preflight_id, 'source_path': 's3://default/uploads/workbook.xlsx', 'action': action},
        )
        requests.append(
            compute_requests_service.create_request(
                test_db_session,
                namespace='default',
                kind=enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_PREFLIGHT,
                command=command,
                request_id=preflight_id if action == enums_pb2.DATASOURCE_PREFLIGHT_ACTION_INITIAL else None,
            )
        )
        requests[-1].status = enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED
        test_db_session.commit()
    assert requests[0].id != requests[1].id
    assert {request.engine_resource_id for request in requests} == {preflight_id}


def test_datasource_enqueue_transfers_preflight_source_ownership_atomically(test_db_session: Session) -> None:
    preflight_id = str(uuid4())
    source_path = 's3://default/uploads/unique-preflight.xlsx'
    initial_command = command_from_payload(
        enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_PREFLIGHT,
        {'preflight_id': preflight_id, 'source_path': source_path, 'action': enums_pb2.DATASOURCE_PREFLIGHT_ACTION_INITIAL, 'delete_source': True},
    )
    preflight = compute_requests_service.stage_request(
        test_db_session, namespace='default', kind=enums_pb2.COMPUTE_REQUEST_KIND_DATASOURCE_PREFLIGHT, command=initial_command, request_id=preflight_id
    )
    test_db_session.commit()
    assert preflight.artifact_path == source_path
    preflight.status = enums_pb2.COMPUTE_REQUEST_STATUS_COMPLETED
    test_db_session.add(preflight)
    test_db_session.commit()
    create = command_from_payload(enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE, {'name': 'Confirmed', 'file_path': source_path, 'file_type': 'excel'})
    accepted = executor_client._submit(
        test_db_session,
        kind=enums_pb2.COMPUTE_REQUEST_KIND_CREATE_FILE_DATASOURCE,
        command=create,
        runtime_probe=SimpleNamespace(),
        source_preflight_id=preflight_id,
    )
    test_db_session.expire_all()
    persisted_preflight = test_db_session.get(type(preflight), preflight_id)
    assert persisted_preflight is not None
    assert persisted_preflight.artifact_path is None
    assert accepted.status == enums_pb2.COMPUTE_REQUEST_STATUS_QUEUED
