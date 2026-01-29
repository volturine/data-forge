"""Limit rows operation."""

from modules.compute.operations.base import OperationParams, make_handler


class LimitParams(OperationParams):
    n: int = 10


LimitHandler = make_handler('limit', LimitParams, lambda lf, p: lf.head(p.n))
