"""Deduplicate rows operation."""

from typing import Literal

from modules.compute.operations.base import OperationParams, make_handler


class DeduplicateParams(OperationParams):
    subset: list[str] | None = None
    keep: Literal['first', 'last', 'any', 'none'] = 'first'


DeduplicateHandler = make_handler(
    'deduplicate',
    DeduplicateParams,
    lambda lf, p: lf.unique(subset=p.subset, keep=p.keep, maintain_order=True),
)
