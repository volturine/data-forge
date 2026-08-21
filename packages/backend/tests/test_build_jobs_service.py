import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlmodel import Session

from backend_core import build_jobs_service
from backend_core.domain.build_jobs.models import BuildJobStatus
from backend_core.persistence.build_jobs.models import BuildJob
from backend_core.transitions import TransitionOutcome


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

    assert renewed.outcome is TransitionOutcome.APPLIED
    assert renewed.value is not None
    assert renewed.value.lease_expires_at is not None
    assert renewed.value.lease_expires_at > previous_expiry
    assert renewed.value.claim_token == claimed.claim_token
    assert renewed.value.lease_generation == claimed.lease_generation
    assert renewed.value.attempts == claimed.attempts


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
    stale_renewal = build_jobs_service.renew_job_lease(
        test_db_session,
        second.id,
        worker_id='worker:one',
        claim_token=first_token,
        lease_generation=first_generation,
    )
    assert stale_renewal.outcome is TransitionOutcome.LEASE_LOST
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


def _claim_and_expire(session: Session, *, worker_id: str) -> BuildJob:
    build_jobs_service.create_job(
        session,
        build_id=str(uuid.uuid4()),
        namespace='default',
        max_attempts=3,
    )
    claimed = build_jobs_service.claim_next_job(session, worker_id=worker_id)
    assert claimed is not None
    claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.add(claimed)
    session.commit()
    return claimed


def test_release_worker_jobs_selects_rows_with_for_update_skip_locked(test_db_session: Session, monkeypatch) -> None:
    claimed = _claim_and_expire(test_db_session, worker_id='worker:one')

    captured = []
    original_execute = test_db_session.execute

    def spy_execute(statement, *args, **kwargs):
        captured.append(statement)
        return original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(test_db_session, 'execute', spy_execute)

    released = build_jobs_service.release_worker_jobs(test_db_session, worker_id='worker:one')

    assert [job.id for job in released] == [claimed.id]
    select_stmts = [stmt for stmt in captured if getattr(stmt, '_for_update_arg', None) is not None]
    assert len(select_stmts) == 1
    assert select_stmts[0]._for_update_arg.skip_locked


def test_release_worker_jobs_blocks_concurrent_transition_until_committed(test_db_session, test_engine, monkeypatch) -> None:
    claimed = _claim_and_expire(test_db_session, worker_id='worker:one')

    competitor_outcome: dict[str, bool] = {}
    original_commit = test_db_session.commit

    def racing_commit() -> None:
        if 'blocked' not in competitor_outcome:
            try:
                with test_engine.connect() as conn:
                    conn.execute(text("SET LOCAL lock_timeout = '300ms'"))
                    conn.execute(
                        text("UPDATE build_jobs SET status = 'FAILED' WHERE id = :job_id"),
                        {'job_id': claimed.id},
                    )
                competitor_outcome['blocked'] = False
            except OperationalError:
                competitor_outcome['blocked'] = True
        original_commit()

    monkeypatch.setattr(test_db_session, 'commit', racing_commit)

    released = build_jobs_service.release_worker_jobs(test_db_session, worker_id='worker:one')

    assert [job.id for job in released] == [claimed.id]
    assert competitor_outcome['blocked'] is True

    test_db_session.expire_all()
    current = test_db_session.get(BuildJob, claimed.id)
    assert current is not None
    assert current.status == BuildJobStatus.QUEUED
    assert current.lease_owner is None
    assert current.claim_token is None


def test_release_worker_jobs_does_not_requeue_after_concurrent_reclaim(test_db_session, test_engine, monkeypatch) -> None:
    claimed = _claim_and_expire(test_db_session, worker_id='worker:one')
    previous_generation = claimed.lease_generation
    previous_attempts = claimed.attempts

    def thief_is_blocked() -> bool:
        with Session(test_engine) as other:
            stolen = build_jobs_service.claim_next_job(other, worker_id='worker:thief')
            other.rollback()
        return stolen is None

    original_commit = test_db_session.commit
    state: dict[str, bool] = {}

    def racing_commit() -> None:
        if 'checked' not in state:
            state['checked'] = True
            # While the release transaction holds the row locks, a competing
            # scheduler using SKIP LOCKED cannot see the rows to reclaim them.
            state['thief_blocked'] = thief_is_blocked()
        original_commit()

    monkeypatch.setattr(test_db_session, 'commit', racing_commit)

    released = build_jobs_service.release_worker_jobs(test_db_session, worker_id='worker:one')

    assert [job.id for job in released] == [claimed.id]
    assert state['thief_blocked'] is True

    test_db_session.expire_all()
    current = test_db_session.get(BuildJob, claimed.id)
    assert current is not None
    assert current.status == BuildJobStatus.QUEUED
    assert current.lease_owner is None

    thief = build_jobs_service.claim_next_job(test_db_session, worker_id='worker:thief')
    assert thief is not None
    assert thief.id == claimed.id
    assert thief.lease_generation == previous_generation + 1
    assert thief.attempts == previous_attempts + 1


def _claim_active(session: Session, *, worker_id: str) -> BuildJob:
    build_jobs_service.create_job(
        session,
        build_id=str(uuid.uuid4()),
        namespace='default',
        max_attempts=3,
    )
    claimed = build_jobs_service.claim_next_job(session, worker_id=worker_id)
    assert claimed is not None
    return claimed


def test_release_worker_jobs_leaves_other_workers_untouched(test_db_session: Session) -> None:
    mine = _claim_active(test_db_session, worker_id='worker:one')
    theirs = _claim_active(test_db_session, worker_id='worker:two')

    mine.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    test_db_session.add(mine)
    test_db_session.commit()

    released = build_jobs_service.release_worker_jobs(test_db_session, worker_id='worker:one')

    assert [job.id for job in released] == [mine.id]
    test_db_session.expire_all()
    still_theirs = test_db_session.get(BuildJob, theirs.id)
    assert still_theirs is not None
    assert still_theirs.status == BuildJobStatus.RUNNING
    assert still_theirs.lease_owner == 'worker:two'
