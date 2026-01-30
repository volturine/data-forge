from modules.compute.operations.base import OperationHandler, OperationParams
from modules.compute.operations.datasource import DatasourceHandler
from modules.compute.operations.deduplicate import DeduplicateHandler
from modules.compute.operations.drop import DropHandler
from modules.compute.operations.explode import ExplodeHandler
from modules.compute.operations.export import ExportHandler
from modules.compute.operations.expression import WithColumnsHandler
from modules.compute.operations.fill_null import FillNullHandler
from modules.compute.operations.filter import FilterHandler
from modules.compute.operations.groupby import GroupByHandler
from modules.compute.operations.join import JoinHandler
from modules.compute.operations.limit import LimitHandler
from modules.compute.operations.null_count import NullCountHandler
from modules.compute.operations.pivot import PivotHandler
from modules.compute.operations.rename import RenameHandler
from modules.compute.operations.sample import SampleHandler
from modules.compute.operations.select import SelectHandler
from modules.compute.operations.sort import SortHandler
from modules.compute.operations.strings import StringTransformHandler
from modules.compute.operations.timeseries import TimeseriesHandler
from modules.compute.operations.topk import TopKHandler
from modules.compute.operations.union import UnionByNameHandler
from modules.compute.operations.unpivot import UnpivotHandler
from modules.compute.operations.value_counts import ValueCountsHandler
from modules.compute.operations.view import ViewHandler

__all__ = [
    # Base
    'OperationHandler',
    'OperationParams',
    # Handlers
    'DatasourceHandler',
    'DeduplicateHandler',
    'DropHandler',
    'ExplodeHandler',
    'ExportHandler',
    'FillNullHandler',
    'FilterHandler',
    'GroupByHandler',
    'JoinHandler',
    'LimitHandler',
    'NullCountHandler',
    'PivotHandler',
    'RenameHandler',
    'SampleHandler',
    'SelectHandler',
    'SortHandler',
    'StringTransformHandler',
    'TimeseriesHandler',
    'TopKHandler',
    'UnionByNameHandler',
    'UnpivotHandler',
    'ValueCountsHandler',
    'ViewHandler',
    'WithColumnsHandler',
    # Registry
    'register_operation',
    'get_operation_handlers',
]

_OPERATION_REGISTRY: dict[str, OperationHandler] = {}


def register_operation(name: str, handler: OperationHandler) -> None:
    if name in _OPERATION_REGISTRY:
        raise ValueError(f'Operation already registered: {name}')
    _OPERATION_REGISTRY[name] = handler


def get_operation_handlers() -> dict[str, OperationHandler]:
    if not _OPERATION_REGISTRY:
        _register_defaults()
    return dict(_OPERATION_REGISTRY)


def _register_defaults() -> None:
    register_operation('datasource', DatasourceHandler())
    register_operation('deduplicate', DeduplicateHandler())
    register_operation('drop', DropHandler())
    register_operation('explode', ExplodeHandler())
    register_operation('export', ExportHandler())
    register_operation('fill_null', FillNullHandler())
    register_operation('filter', FilterHandler())
    register_operation('groupby', GroupByHandler())
    register_operation('join', JoinHandler())
    register_operation('limit', LimitHandler())
    register_operation('null_count', NullCountHandler())
    register_operation('pivot', PivotHandler())
    register_operation('rename', RenameHandler())
    register_operation('sample', SampleHandler())
    register_operation('select', SelectHandler())
    register_operation('sort', SortHandler())
    register_operation('string_transform', StringTransformHandler())
    register_operation('timeseries', TimeseriesHandler())
    register_operation('topk', TopKHandler())
    register_operation('union_by_name', UnionByNameHandler())
    register_operation('unpivot', UnpivotHandler())
    register_operation('value_counts', ValueCountsHandler())
    register_operation('view', ViewHandler())
    register_operation('with_columns', WithColumnsHandler())
