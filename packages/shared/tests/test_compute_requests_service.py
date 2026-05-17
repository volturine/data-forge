from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from contracts.compute_requests.models import ComputeRequest, ComputeRequestKind, ComputeRequestStatus
from core import compute_requests_service


def test_mark_request_failed_recovers_from_pending_rollback(test_db_session) -> None:
    request = compute_requests_service.create_request(test_db_session, namespace='default', kind=ComputeRequestKind.PREVIEW, request_json={'example': True})
    request_id = request.id

    duplicate = (
        ComputeRequest.metadata.tables[ComputeRequest.__tablename__]
        .insert()
        .values(
            id=request_id,
            namespace='default',
            kind=ComputeRequestKind.PREVIEW,
            status=ComputeRequestStatus.QUEUED,
            request_json={'duplicate': True},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError):
        test_db_session.execute(duplicate)
        test_db_session.commit()

    failed = compute_requests_service.mark_request_failed(
        test_db_session, request_id, error_message='boom', response_json={'error': 'boom', 'status_code': 500}
    )

    assert failed.status == ComputeRequestStatus.FAILED
    assert failed.error_message == 'boom'
    assert failed.response_json == {'error': 'boom', 'status_code': 500}
    assert failed.completed_at is not None
