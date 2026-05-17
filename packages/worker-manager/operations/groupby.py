from collections.abc import Callable
from dataclasses import dataclass

import polars as pl
from contracts.compute.base import OperationHandler, OperationParams
from contracts.step_config_enums import GroupByAggregationFunction
from pydantic import BaseModel, ConfigDict


class AggregationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str
    function: GroupByAggregationFunction
    alias: str | None = None


class GroupByParams(OperationParams):
    group_by: list[str]
    aggregations: list[AggregationSpec]


GroupByAggregationExpr = Callable[[str], pl.Expr]


@dataclass(frozen=True, slots=True)
class GroupByAggregationDefinition:
    function: GroupByAggregationFunction
    expr_factory: GroupByAggregationExpr

    @classmethod
    def require(cls, value: GroupByAggregationFunction | str) -> "GroupByAggregationDefinition":
        try:
            function = GroupByAggregationFunction.require(value)
        except ValueError as exc:
            raise ValueError(f"Unsupported aggregation function: {value}") from exc
        return GROUPBY_AGGREGATION_DEFINITIONS[function]

    def apply(self, column: str) -> pl.Expr:
        return self.expr_factory(column)


GROUPBY_AGGREGATION_DEFINITIONS: dict[GroupByAggregationFunction, GroupByAggregationDefinition] = {
    GroupByAggregationFunction.SUM: GroupByAggregationDefinition(GroupByAggregationFunction.SUM, lambda column: pl.col(column).sum()),
    GroupByAggregationFunction.MEAN: GroupByAggregationDefinition(GroupByAggregationFunction.MEAN, lambda column: pl.col(column).mean()),
    GroupByAggregationFunction.COUNT: GroupByAggregationDefinition(GroupByAggregationFunction.COUNT, lambda column: pl.col(column).count()),
    GroupByAggregationFunction.MIN: GroupByAggregationDefinition(GroupByAggregationFunction.MIN, lambda column: pl.col(column).min()),
    GroupByAggregationFunction.MAX: GroupByAggregationDefinition(GroupByAggregationFunction.MAX, lambda column: pl.col(column).max()),
    GroupByAggregationFunction.FIRST: GroupByAggregationDefinition(GroupByAggregationFunction.FIRST, lambda column: pl.col(column).first()),
    GroupByAggregationFunction.LAST: GroupByAggregationDefinition(GroupByAggregationFunction.LAST, lambda column: pl.col(column).last()),
    GroupByAggregationFunction.MEDIAN: GroupByAggregationDefinition(GroupByAggregationFunction.MEDIAN, lambda column: pl.col(column).median()),
    GroupByAggregationFunction.STD: GroupByAggregationDefinition(GroupByAggregationFunction.STD, lambda column: pl.col(column).std()),
    GroupByAggregationFunction.N_UNIQUE: GroupByAggregationDefinition(GroupByAggregationFunction.N_UNIQUE, lambda column: pl.col(column).n_unique()),
    GroupByAggregationFunction.COLLECT_LIST: GroupByAggregationDefinition(
        GroupByAggregationFunction.COLLECT_LIST,
        lambda column: pl.col(column).implode(),
    ),
    GroupByAggregationFunction.COLLECT_SET: GroupByAggregationDefinition(
        GroupByAggregationFunction.COLLECT_SET,
        lambda column: pl.col(column).implode().list.unique(),
    ),
}


class GroupByHandler(OperationHandler):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = GroupByParams.model_validate(params)
        exprs = [
            GroupByAggregationDefinition.require(aggregation.function)
            .apply(aggregation.column)
            .alias(aggregation.alias or aggregation.function.default_alias(aggregation.column))
            for aggregation in validated.aggregations
        ]
        return lf.group_by(validated.group_by).agg(exprs)
