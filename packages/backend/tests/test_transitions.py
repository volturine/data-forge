import logging
from typing import Any, cast

import pytest

from backend_core.lease_observability import record_lease_transition
from backend_core.transitions import TransitionOutcome


def test_lease_transition_records_redacted_context(caplog: pytest.LogCaptureFixture) -> None:
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

    record = cast(Any, caplog.records[-1])
    assert record.runtime_kind == 'build_job'
    assert record.runtime_transition == 'renew'
    assert record.runtime_outcome == 'lease_lost'
    assert record.runtime_entity_id == 'job-1'
    assert record.runtime_claim_token == '12345678'
    assert 'secret' not in record.getMessage()
