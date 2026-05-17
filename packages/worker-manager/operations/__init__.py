from contracts.compute.base import OperationHandler, OperationParams

from operations.ai import AIHandler
from operations.datasource import DatasourceHandler
from operations.deduplicate import DeduplicateHandler
from operations.download import DownloadHandler
from operations.drop import DropHandler
from operations.explode import ExplodeHandler
from operations.export import ExportHandler
from operations.expression import ExpressionHandler
from operations.fill_null import FillNullHandler
from operations.filter import FilterHandler
from operations.groupby import GroupByHandler
from operations.join import JoinHandler
from operations.limit import LimitHandler
from operations.notification import NotificationHandler
from operations.pivot import PivotHandler
from operations.plot import ChartHandler
from operations.rename import RenameHandler
from operations.sample import SampleHandler
from operations.select import SelectHandler
from operations.sort import SortHandler
from operations.strings import StringTransformHandler
from operations.timeseries import TimeseriesHandler
from operations.topk import TopKHandler
from operations.union import UnionByNameHandler
from operations.unpivot import UnpivotHandler
from operations.view import ViewHandler
from operations.with_columns import WithColumnsHandler

__all__ = [
    "HANDLERS",
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
