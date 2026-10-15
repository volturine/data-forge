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
from runtime.domain.compute.base import OperationHandler, OperationParams

__all__ = [
    "HANDLERS",
    "PARAM_MODELS",
    "OperationHandler",
    "OperationParams",
]

# One registry keeps every executable step's handler and parameter model in sync.
_OPERATIONS: dict[str, tuple[OperationHandler, type[OperationParams]]] = {
    "datasource": (DatasourceHandler(), DatasourceParams),
    "ai": (AIHandler(), AIParams),
    "deduplicate": (DeduplicateHandler(), DeduplicateParams),
    "download": (DownloadHandler(), DownloadParams),
    "drop": (DropHandler(), DropParams),
    "explode": (ExplodeHandler(), ExplodeParams),
    "export": (ExportHandler(), ExportParams),
    "fill_null": (FillNullHandler(), FillNullParams),
    "filter": (FilterHandler(), FilterParams),
    "groupby": (GroupByHandler(), GroupByParams),
    "join": (JoinHandler(), JoinParams),
    "limit": (LimitHandler(), LimitParams),
    "notification": (NotificationHandler(), NotificationParams),
    "pivot": (PivotHandler(), PivotParams),
    "rename": (RenameHandler(), RenameParams),
    "sample": (SampleHandler(), SampleParams),
    "select": (SelectHandler(), SelectParams),
    "sort": (SortHandler(), SortParams),
    "string_transform": (StringTransformHandler(), StringTransformParams),
    "timeseries": (TimeseriesHandler(), TimeseriesParams),
    "topk": (TopKHandler(), TopKParams),
    "union_by_name": (UnionByNameHandler(), UnionParams),
    "unpivot": (UnpivotHandler(), UnpivotParams),
    "view": (ViewHandler(), ViewParams),
    "with_columns": (WithColumnsHandler(), WithColumnsParams),
    "expression": (ExpressionHandler(), ExpressionParams),
    "chart": (ChartHandler(), ChartParams),
}

HANDLERS: dict[str, OperationHandler] = {name: handler for name, (handler, _params) in _OPERATIONS.items()}
PARAM_MODELS: dict[str, type[OperationParams]] = {name: params for name, (_handler, params) in _OPERATIONS.items()}
