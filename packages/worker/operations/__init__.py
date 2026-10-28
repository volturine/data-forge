from collections.abc import Callable
from dataclasses import dataclass

import polars as pl

from operations import (
    ai,
    datasource,
    deduplicate,
    download,
    drop,
    explode,
    export,
    expression,
    fill_null,
    filter,
    groupby,
    join,
    limit,
    notification,
    pivot,
    plot,
    rename,
    sample,
    select,
    sort,
    strings,
    timeseries,
    topk,
    union,
    unpivot,
    view,
    with_columns,
)
from runtime.domain.compute.base import OperationParams

__all__ = [
    "OPERATIONS",
    "PARAM_MODELS",
    "Operation",
    "OperationParams",
]


def passthrough(lf: pl.LazyFrame, params: OperationParams, **_) -> pl.LazyFrame:
    """Return the input frame unchanged; the step's parameters are validated during conversion."""
    return lf


@dataclass(frozen=True, slots=True)
class Operation:
    params: type[OperationParams]
    apply: Callable[..., pl.LazyFrame]


# One registry keeps every executable step's function and parameter model in sync.
OPERATIONS: dict[str, Operation] = {
    "datasource": Operation(datasource.DatasourceParams, datasource.datasource),
    "ai": Operation(ai.AIParams, ai.ai),
    "deduplicate": Operation(deduplicate.DeduplicateParams, deduplicate.deduplicate),
    "download": Operation(download.DownloadParams, passthrough),
    "drop": Operation(drop.DropParams, drop.drop),
    "explode": Operation(explode.ExplodeParams, explode.explode),
    "export": Operation(export.ExportParams, passthrough),
    "fill_null": Operation(fill_null.FillNullParams, fill_null.fill_null),
    "filter": Operation(filter.FilterParams, filter.filter),
    "groupby": Operation(groupby.GroupByParams, groupby.groupby),
    "join": Operation(join.JoinParams, join.join),
    "limit": Operation(limit.LimitParams, limit.limit),
    "notification": Operation(notification.NotificationParams, notification.notification),
    "pivot": Operation(pivot.PivotParams, pivot.pivot),
    "rename": Operation(rename.RenameParams, rename.rename),
    "sample": Operation(sample.SampleParams, sample.sample),
    "select": Operation(select.SelectParams, select.select),
    "sort": Operation(sort.SortParams, sort.sort),
    "string_transform": Operation(strings.StringTransformParams, strings.string_transform),
    "timeseries": Operation(timeseries.TimeseriesParams, timeseries.timeseries),
    "topk": Operation(topk.TopKParams, topk.topk),
    "union_by_name": Operation(union.UnionParams, union.union_by_name),
    "unpivot": Operation(unpivot.UnpivotParams, unpivot.unpivot),
    "view": Operation(view.ViewParams, passthrough),
    "with_columns": Operation(with_columns.WithColumnsParams, with_columns.with_columns),
    "expression": Operation(expression.ExpressionParams, expression.expression),
    "chart": Operation(plot.ChartParams, passthrough),
}

PARAM_MODELS: dict[str, type[OperationParams]] = {name: operation.params for name, operation in OPERATIONS.items()}
