from collections.abc import Callable

import polars as pl
from pydantic import BaseModel, ConfigDict

from modules.compute.core.base import OperationHandler, OperationParams


class AggregationSpec(BaseModel):
    model_config = ConfigDict(extra='forbid')

    column: str
    function: str
    alias: str | None = None


class GroupByParams(OperationParams):
    group_by: list[str]
    aggregations: list[AggregationSpec]


class GroupByHandler(OperationHandler):
    AGG_FUNCTIONS: dict[str, Callable[[str], pl.Expr]] = {
        'sum': lambda col: pl.col(col).sum(),
        'mean': lambda col: pl.col(col).mean(),
        'count': lambda col: pl.col(col).count(),
        'min': lambda col: pl.col(col).min(),
        'max': lambda col: pl.col(col).max(),
        'first': lambda col: pl.col(col).first(),
        'last': lambda col: pl.col(col).last(),
        'median': lambda col: pl.col(col).median(),
        'std': lambda col: pl.col(col).std(),
        'var': lambda col: pl.col(col).var(),
        'collect_list': lambda col: pl.col(col).implode(),
        'collect_set': lambda col: pl.col(col).implode().list.unique(),
    }

    @property
    def name(self) -> str:
        return 'groupby'

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame:
        validated = GroupByParams.model_validate(params)
        exprs: list[pl.Expr] = []
        for agg in validated.aggregations:
            expr = self._get_aggregation(agg.function)(agg.column)
            alias = agg.alias or f'{agg.column}_{agg.function}'
            exprs.append(expr.alias(alias))
        return lf.group_by(validated.group_by).agg(exprs)

    def _get_aggregation(self, name: str) -> Callable[[str], pl.Expr]:
        agg = self.AGG_FUNCTIONS.get(name)
        if not agg:
            raise ValueError(f'Unsupported aggregation function: {name}')
        return agg


def get_aggregation(name: str) -> Callable[[str], pl.Expr]:
    return GroupByHandler()._get_aggregation(name)
