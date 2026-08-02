from collections.abc import Iterable

from sqlmodel import Session

from backend_core.persistence.healthchecks.models import HealthCheckResult
from backend_core.transactions import committed


@committed
def record_results(session: Session, results: Iterable[HealthCheckResult]) -> int:
    records = list(results)
    session.add_all(records)
    return len(records)
