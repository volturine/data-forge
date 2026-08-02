from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Mapping
from threading import Lock

from backend_core.transitions import TransitionOutcome

logger = logging.getLogger('dataforge.runtime.leases')

_counts: Counter[tuple[str, str, str]] = Counter()
_lock = Lock()


def record_lease_transition(
    *,
    kind: str,
    transition: str,
    outcome: TransitionOutcome,
    entity_id: str,
    owner_id: str,
    claim_token: str,
    generation: int,
    attempt: int | None = None,
) -> None:
    with _lock:
        _counts[(kind, transition, outcome.value)] += 1
    logger.info(
        'runtime lease transition',
        extra={
            'runtime_kind': kind,
            'runtime_transition': transition,
            'runtime_outcome': outcome.value,
            'runtime_entity_id': entity_id,
            'runtime_owner_id': owner_id,
            'runtime_claim_token': claim_token[:8],
            'runtime_generation': generation,
            'runtime_attempt': attempt,
        },
    )


def lease_transition_counts() -> Mapping[tuple[str, str, str], int]:
    with _lock:
        return dict(_counts)


def reset_lease_transition_counts() -> None:
    with _lock:
        _counts.clear()
