from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TransitionOutcome(StrEnum):
    APPLIED = 'applied'
    ALREADY_APPLIED = 'already_applied'
    ALREADY_TERMINAL = 'already_terminal'
    LEASE_LOST = 'lease_lost'
    INVALID_TRANSITION = 'invalid_transition'
    NOT_FOUND = 'not_found'


@dataclass(frozen=True)
class TransitionResult[T]:
    outcome: TransitionOutcome
    value: T | None = None

    @property
    def applied(self) -> bool:
        return self.outcome is TransitionOutcome.APPLIED


def applied[T](value: T) -> TransitionResult[T]:
    return TransitionResult(outcome=TransitionOutcome.APPLIED, value=value)


def rejected[T](outcome: TransitionOutcome) -> TransitionResult[T]:
    if outcome is TransitionOutcome.APPLIED:
        raise ValueError('Applied transitions require a value')
    return TransitionResult(outcome=outcome)
