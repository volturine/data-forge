from __future__ import annotations

from enum import StrEnum


class TransitionOutcome(StrEnum):
    APPLIED = 'applied'
    ALREADY_APPLIED = 'already_applied'
    ALREADY_TERMINAL = 'already_terminal'
    LEASE_LOST = 'lease_lost'
    INVALID_TRANSITION = 'invalid_transition'
    NOT_FOUND = 'not_found'
