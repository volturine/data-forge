import logging
from typing import Any, cast

import pytest

from backend_core.lease_observability import lease_transition_counts, record_lease_transition, reset_lease_transition_counts
from backend_core.transitions import TransitionOutcome, TransitionResult, applied, rejected


@pytest.fixture(autouse=True)
def _reset_counts() -> None:
    reset_lease_transition_counts()


def test_transition_result_exposes_typed_outcome() -> None:
    accepted = applied('value')
    stale: TransitionResult[str] = rejected(TransitionOutcome.LEASE_LOST)

    assert accepted.applied
    assert accepted.value == 'value'
    assert not stale.applied
    assert stale.value is None


def test_lease_transition_records_counter_and_redacted_context(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger='dataforge.runtime.leases')

    record_lease_transition(
        kind='build_job',
        transition='renew',
        outcome=TransitionOutcome.LEASE_LOST,
        entity_id='job-1',
        owner_id='worker-1',
        claim_token='1234567890-secret',
        generation=4,
        attempt=2,
    )

    assert lease_transition_counts() == {('build_job', 'renew', 'lease_lost'): 1}
    record = cast(Any, caplog.records[-1])
    assert record.runtime_entity_id == 'job-1'
    assert record.runtime_claim_token == '12345678'
    assert 'secret' not in record.getMessage()
