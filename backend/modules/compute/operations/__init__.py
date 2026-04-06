from modules.compute.core.base import OperationHandler, OperationParams
from modules.compute.operations.ai import AIHandler
from modules.compute.operations.datasource import DatasourceHandler
from modules.compute.operations.deduplicate import DeduplicateHandler
from modules.compute.operations.download import DownloadHandler
from modules.compute.operations.drop import DropHandler
from modules.compute.operations.explode import ExplodeHandler
from modules.compute.operations.export import ExportHandler
from modules.compute.operations.expression import ExpressionHandler
from modules.compute.operations.fill_null import FillNullHandler
from modules.compute.operations.filter import FilterHandler
from modules.compute.operations.groupby import GroupByHandler
from modules.compute.operations.join import JoinHandler
from modules.compute.operations.limit import LimitHandler
from modules.compute.operations.notification import NotificationHandler
from modules.compute.operations.pivot import PivotHandler
from modules.compute.operations.plot import ChartHandler
from modules.compute.operations.rename import RenameHandler
from modules.compute.operations.sample import SampleHandler
from modules.compute.operations.select import SelectHandler
from modules.compute.operations.sort import SortHandler
from modules.compute.operations.strings import StringTransformHandler
from modules.compute.operations.timeseries import TimeseriesHandler
from modules.compute.operations.topk import TopKHandler
from modules.compute.operations.union import UnionByNameHandler
from modules.compute.operations.unpivot import UnpivotHandler
from modules.compute.operations.view import ViewHandler
from modules.compute.operations.with_columns import WithColumnsHandler

__all__ = [
    'HANDLERS',
    'OperationHandler',
    'OperationParams',
]

HANDLERS: dict[str, OperationHandler] = {
    'datasource': DatasourceHandler(),
    'ai': AIHandler(),
    'deduplicate': DeduplicateHandler(),
    'download': DownloadHandler(),
    'drop': DropHandler(),
    'explode': ExplodeHandler(),
    'export': ExportHandler(),
    'fill_null': FillNullHandler(),
    'filter': FilterHandler(),
    'groupby': GroupByHandler(),
    'join': JoinHandler(),
    'limit': LimitHandler(),
    'notification': NotificationHandler(),
    'pivot': PivotHandler(),
    'rename': RenameHandler(),
    'sample': SampleHandler(),
    'select': SelectHandler(),
    'sort': SortHandler(),
    'string_transform': StringTransformHandler(),
    'timeseries': TimeseriesHandler(),
    'topk': TopKHandler(),
    'union_by_name': UnionByNameHandler(),
    'unpivot': UnpivotHandler(),
    'view': ViewHandler(),
    'with_columns': WithColumnsHandler(),
    'expression': ExpressionHandler(),
    'chart': ChartHandler(),
}
