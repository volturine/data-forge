"""Derive the private 50-tab load-probe CPU limit from its DIND budget."""

from __future__ import annotations

import sys
from decimal import Decimal, InvalidOperation


def load_probe_cpu_limit(dind_cpus: str) -> Decimal:
    try:
        dind_budget = Decimal(dind_cpus)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid DIND CPU budget: {dind_cpus!r}") from exc
    if not dind_budget.is_finite() or dind_budget <= 0:
        raise ValueError(f"DIND CPU budget must be positive and finite: {dind_cpus!r}")
    return min(Decimal("3.0"), dind_budget * Decimal("0.4"))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: load_probe_cpu_budget.py DIND_CPUS")
    try:
        print(f"{load_probe_cpu_limit(sys.argv[1]):.3f}")
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
