import uuid
from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from backend_core import build_jobs_service
from backend_core.domain.build_jobs.models import BuildJobStatus
from backend_core.persistence.build_jobs.models import BuildJob


def test_claim_assigns_unique_fencing_identity(test_db_session: Session) -> None:
    job = build_jobs_service.create_job(
        test_db_session,
        build_id=str(uuid.uuid4()),
        namespace='default',
        max_attempts=2,
    )

    claimed = build_jobs_service.claim_next_job(test_db_session, worker_id='worker:one')

    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.status == BuildJobStatus.RUNNING
    assert claimed.lease_owner == 'worker:one'
    assert claimed.claim_token is not None
    assert claimed.lease_generation == 1
    assert claimed.attempts == 1
    assert claimed.claimed_at is not None
    assert claimed.last_renewed_at is not None
    assert claimed.lease_expires_at is not None


def test_renew_extends_only_the_active_claim(test_db_session: Session) -> None:
    build_jobs_service.create_job(
        test_db_session,
        build_id=str(uuid.uuid4()),
        namespace='default',
        max_attempts=2,
    )
    claimed = build_jobs_service.claim_next_job(test_db_session, worker_id='worker:one')
    assert claimed is not None
    assert claimed.claim_token is not None
    claimed.lease_expires_at = datetime.now(UTC) + timedelta(seconds=10)
    test_db_session.add(claimed)
    test_db_session.commit()
    previous_expiry = claimed.lease_expires_at

    renewed = build_jobs_service.renew_job_lease(
        test_db_session,
        claimed.id,
        worker_id='worker:one',
        claim_token=claimed.claim_token,
        lease_generation=claimed.lease_generation,
    )

    assert renewed is not None
    assert renewed.lease_expires_at is not None
    assert renewed.lease_expires_at > previous_expiry
    assert renewed.claim_token == claimed.claim_token
    assert renewed.lease_generation == claimed.lease_generation
    assert renewed.attempts == claimed.attempts


def test_stale_claim_cannot_renew_or_complete_after_reclaim(test_db_session: Session) -> None:
    build_jobs_service.create_job(
        test_db_session,
        build_id=str(uuid.uuid4()),
        namespace='default',
        max_attempts=2,
    )
    first = build_jobs_service.claim_next_job(test_db_session, worker_id='worker:one')
    assert first is not None
    assert first.claim_token is not None
    first_token = first.claim_token
    first_generation = first.lease_generation
    first.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    test_db_session.add(first)
    test_db_session.commit()

    second = build_jobs_service.claim_next_job(test_db_session, worker_id='worker:two')

    assert second is not None
    assert second.claim_token is not None
    assert second.claim_token != first_token
    assert second.lease_generation == first_generation + 1
    assert second.lease_owner == 'worker:two'
    assert (
        build_jobs_service.renew_job_lease(
            test_db_session,
            second.id,
            worker_id='worker:one',
            claim_token=first_token,
            lease_generation=first_generation,
        )
        is None
    )
    assert (
        build_jobs_service.finish_claimed_job(
            test_db_session,
            second.id,
            worker_id='worker:one',
            build_id=second.build_id,
            claim_token=first_token,
            lease_generation=first_generation,
            status=BuildJobStatus.COMPLETED,
        )
        is None
    )

    test_db_session.expire_all()
    current = test_db_session.get(BuildJob, second.id)
    assert current is not None
    assert current.status == BuildJobStatus.RUNNING
    assert current.lease_owner == 'worker:two'
    assert current.claim_token == second.claim_token
    assert current.lease_generation == second.lease_generation

    completed = build_jobs_service.finish_claimed_job(
        test_db_session,
        second.id,
        worker_id='worker:two',
        build_id=second.build_id,
        claim_token=second.claim_token,
        lease_generation=second.lease_generation,
        status=BuildJobStatus.COMPLETED,
    )
    assert completed is not None
    assert completed.status == BuildJobStatus.COMPLETED
    assert completed.lease_owner is None
    assert completed.claim_token is None
    test_db_session.commit()


def test_terminal_job_rejects_replayed_claim_completion(test_db_session: Session) -> None:
    build_jobs_service.create_job(test_db_session, build_id=str(uuid.uuid4()), namespace='default')
    claimed = build_jobs_service.claim_next_job(test_db_session, worker_id='worker:one')
    assert claimed is not None
    assert claimed.claim_token is not None

    completed = build_jobs_service.finish_claimed_job(
        test_db_session,
        claimed.id,
        worker_id='worker:one',
        build_id=claimed.build_id,
        claim_token=claimed.claim_token,
        lease_generation=claimed.lease_generation,
        status=BuildJobStatus.COMPLETED,
    )
    replayed = build_jobs_service.finish_claimed_job(
        test_db_session,
        claimed.id,
        worker_id='worker:one',
        build_id=claimed.build_id,
        claim_token=claimed.claim_token,
        lease_generation=claimed.lease_generation,
        status=BuildJobStatus.FAILED,
        error='late failure',
    )

    assert completed is not None
    assert replayed is None
    test_db_session.commit()
    test_db_session.expire_all()
    current = test_db_session.get(BuildJob, claimed.id)
    assert current is not None
    assert current.status == BuildJobStatus.COMPLETED
    assert current.last_error is None

    cancelled = build_jobs_service.mark_job_cancelled(test_db_session, claimed.id)
    assert cancelled.status == BuildJobStatus.COMPLETED


def test_finish_rejects_mismatched_build_id(test_db_session: Session) -> None:
    build_jobs_service.create_job(test_db_session, build_id=str(uuid.uuid4()), namespace='default')
    claimed = build_jobs_service.claim_next_job(test_db_session, worker_id='worker:one')
    assert claimed is not None
    assert claimed.claim_token is not None

    result = build_jobs_service.finish_claimed_job(
        test_db_session,
        claimed.id,
        worker_id='worker:one',
        build_id=str(uuid.uuid4()),
        claim_token=claimed.claim_token,
        lease_generation=claimed.lease_generation,
        status=BuildJobStatus.COMPLETED,
    )

    assert result is None
    test_db_session.expire_all()
    current = test_db_session.get(BuildJob, claimed.id)
    assert current is not None
    assert current.status == BuildJobStatus.RUNNING
    assert current.claim_token == claimed.claim_token


def test_queued_job_can_be_cancelled_before_claim(test_db_session: Session) -> None:
    job = build_jobs_service.create_job(test_db_session, build_id=str(uuid.uuid4()), namespace='default')

    cancelled = build_jobs_service.mark_job_cancelled(test_db_session, job.id)

    assert cancelled.status == BuildJobStatus.CANCELLED
    assert build_jobs_service.claim_next_job(test_db_session, worker_id='worker:one') is None


def test_expired_default_claim_is_failed_when_attempts_are_exhausted(test_db_session: Session) -> None:
    build_jobs_service.create_job(test_db_session, build_id=str(uuid.uuid4()), namespace='default')
    claimed = build_jobs_service.claim_next_job(test_db_session, worker_id='worker:one')
    assert claimed is not None
    claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    test_db_session.add(claimed)
    test_db_session.commit()

    expired_build_ids = build_jobs_service.expire_exhausted_jobs(test_db_session)

    assert expired_build_ids == [claimed.build_id]
    test_db_session.expire_all()
    current = test_db_session.get(BuildJob, claimed.id)
    assert current is not None
    assert current.status == BuildJobStatus.FAILED
    assert current.last_error == 'Build job lease expired after maximum attempts'
    assert current.lease_owner is None
    assert current.claim_token is None
