from collections.abc import Callable

import polars as pl
from pydantic import BaseModel, ConfigDict

from operations.enums import GroupByAggregationFunction
from runtime.domain.compute.base import OperationParams


class AggregationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str
    function: GroupByAggregationFunction
    alias: str | None = None


class GroupByParams(OperationParams):
    group_by: list[str]
    aggregations: list[AggregationSpec]


GroupByAggregationExpr = Callable[[str], pl.Expr]

GROUPBY_AGGREGATION_EXPRS: dict[GroupByAggregationFunction, GroupByAggregationExpr] = {
    GroupByAggregationFunction.SUM: lambda column: pl.col(column).sum(),
    GroupByAggregationFunction.MEAN: lambda column: pl.col(column).mean(),
    GroupByAggregationFunction.COUNT: lambda column: pl.col(column).count(),
    GroupByAggregationFunction.MIN: lambda column: pl.col(column).min(),
    GroupByAggregationFunction.MAX: lambda column: pl.col(column).max(),
    GroupByAggregationFunction.FIRST: lambda column: pl.col(column).first(),
    GroupByAggregationFunction.LAST: lambda column: pl.col(column).last(),
    GroupByAggregationFunction.MEDIAN: lambda column: pl.col(column).median(),
    GroupByAggregationFunction.STD: lambda column: pl.col(column).std(),
    GroupByAggregationFunction.N_UNIQUE: lambda column: pl.col(column).n_unique(),
    GroupByAggregationFunction.COLLECT_LIST: lambda column: pl.col(column).implode(),
    GroupByAggregationFunction.COLLECT_SET: lambda column: pl.col(column).implode().list.unique(),
}


def groupby(lf: pl.LazyFrame, params: GroupByParams, **_) -> pl.LazyFrame:
    exprs = [
        GROUPBY_AGGREGATION_EXPRS[aggregation.function](aggregation.column).alias(aggregation.alias or aggregation.function.default_alias(aggregation.column))
        for aggregation in params.aggregations
    ]
    return lf.group_by(params.group_by, maintain_order=True).agg(exprs)
