from operations.ai import AIHandler, AIParams
from operations.datasource import DatasourceHandler, DatasourceParams
from operations.deduplicate import DeduplicateHandler, DeduplicateParams
from operations.download import DownloadHandler, DownloadParams
from operations.drop import DropHandler, DropParams
from operations.explode import ExplodeHandler, ExplodeParams
from operations.export import ExportHandler, ExportParams
from operations.expression import ExpressionHandler, ExpressionParams
from operations.fill_null import FillNullHandler, FillNullParams
from operations.filter import FilterHandler, FilterParams
from operations.groupby import GroupByHandler, GroupByParams
from operations.join import JoinHandler, JoinParams
from operations.limit import LimitHandler, LimitParams
from operations.notification import NotificationHandler, NotificationParams
from operations.pivot import PivotHandler, PivotParams
from operations.plot import ChartHandler, ChartParams
from operations.rename import RenameHandler, RenameParams
from operations.sample import SampleHandler, SampleParams
from operations.select import SelectHandler, SelectParams
from operations.sort import SortHandler, SortParams
from operations.strings import StringTransformHandler, StringTransformParams
from operations.timeseries import TimeseriesHandler, TimeseriesParams
from operations.topk import TopKHandler, TopKParams
from operations.union import UnionByNameHandler, UnionParams
from operations.unpivot import UnpivotHandler, UnpivotParams
from operations.view import ViewHandler, ViewParams
from operations.with_columns import WithColumnsHandler, WithColumnsParams
from runtime.models.compute.base import OperationHandler, OperationParams

__all__ = [
    "HANDLERS",
    "PARAM_MODELS",
    "OperationHandler",
    "OperationParams",
]

HANDLERS: dict[str, OperationHandler] = {
    "datasource": DatasourceHandler(),
    "ai": AIHandler(),
    "deduplicate": DeduplicateHandler(),
    "download": DownloadHandler(),
    "drop": DropHandler(),
    "explode": ExplodeHandler(),
    "export": ExportHandler(),
    "fill_null": FillNullHandler(),
    "filter": FilterHandler(),
    "groupby": GroupByHandler(),
    "join": JoinHandler(),
    "limit": LimitHandler(),
    "notification": NotificationHandler(),
    "pivot": PivotHandler(),
    "rename": RenameHandler(),
    "sample": SampleHandler(),
    "select": SelectHandler(),
    "sort": SortHandler(),
    "string_transform": StringTransformHandler(),
    "timeseries": TimeseriesHandler(),
    "topk": TopKHandler(),
    "union_by_name": UnionByNameHandler(),
    "unpivot": UnpivotHandler(),
    "view": ViewHandler(),
    "with_columns": WithColumnsHandler(),
    "expression": ExpressionHandler(),
    "chart": ChartHandler(),
}

PARAM_MODELS: dict[str, type[OperationParams]] = {
    "datasource": DatasourceParams,
    "ai": AIParams,
    "deduplicate": DeduplicateParams,
    "download": DownloadParams,
    "drop": DropParams,
    "explode": ExplodeParams,
    "export": ExportParams,
    "fill_null": FillNullParams,
    "filter": FilterParams,
    "groupby": GroupByParams,
    "join": JoinParams,
    "limit": LimitParams,
    "notification": NotificationParams,
    "pivot": PivotParams,
    "rename": RenameParams,
    "sample": SampleParams,
    "select": SelectParams,
    "sort": SortParams,
    "string_transform": StringTransformParams,
    "timeseries": TimeseriesParams,
    "topk": TopKParams,
    "union_by_name": UnionParams,
    "unpivot": UnpivotParams,
    "view": ViewParams,
    "with_columns": WithColumnsParams,
    "expression": ExpressionParams,
    "chart": ChartParams,
}
