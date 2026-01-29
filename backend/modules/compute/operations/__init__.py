from modules.compute.operations.base import OperationHandler
from modules.compute.operations.datasource import DatasourceHandler
from modules.compute.operations.fill_null import FillNullHandler
from modules.compute.operations.filter import FilterHandler
from modules.compute.operations.groupby import GroupByHandler
from modules.compute.operations.join import JoinHandler
from modules.compute.operations.pivot import PivotHandler
from modules.compute.operations.simple import (
    DeduplicateHandler,
    DropHandler,
    ExplodeHandler,
    ExportHandler,
    LimitHandler,
    NullCountHandler,
    RenameHandler,
    SampleHandler,
    SelectHandler,
    SortHandler,
    TopKHandler,
    UnpivotHandler,
    ValueCountsHandler,
    ViewHandler,
    WithColumnsHandler,
)
from modules.compute.operations.strings import StringTransformHandler
from modules.compute.operations.timeseries import TimeseriesHandler
from modules.compute.operations.union import UnionByNameHandler

__all__ = [
    'OperationHandler',
    'DatasourceHandler',
    'FillNullHandler',
    'FilterHandler',
    'GroupByHandler',
    'JoinHandler',
    'PivotHandler',
    'DeduplicateHandler',
    'DropHandler',
    'ExplodeHandler',
    'ExportHandler',
    'LimitHandler',
    'NullCountHandler',
    'RenameHandler',
    'SampleHandler',
    'SelectHandler',
    'SortHandler',
    'TopKHandler',
    'UnpivotHandler',
    'ValueCountsHandler',
    'ViewHandler',
    'WithColumnsHandler',
    'StringTransformHandler',
    'TimeseriesHandler',
    'UnionByNameHandler',
    'DatasourceHandler',
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
    register_operation('filter', FilterHandler())
    register_operation('select', SelectHandler())
    register_operation('groupby', GroupByHandler())
    register_operation('sort', SortHandler())
    register_operation('rename', RenameHandler())
    register_operation('with_columns', WithColumnsHandler())
    register_operation('drop', DropHandler())
    register_operation('pivot', PivotHandler())
    register_operation('timeseries', TimeseriesHandler())
    register_operation('string_transform', StringTransformHandler())
    register_operation('fill_null', FillNullHandler())
    register_operation('deduplicate', DeduplicateHandler())
    register_operation('explode', ExplodeHandler())
    register_operation('view', ViewHandler())
    register_operation('unpivot', UnpivotHandler())
    register_operation('join', JoinHandler())
    register_operation('sample', SampleHandler())
    register_operation('limit', LimitHandler())
    register_operation('topk', TopKHandler())
    register_operation('null_count', NullCountHandler())
    register_operation('value_counts', ValueCountsHandler())
    register_operation('export', ExportHandler())
    register_operation('union_by_name', UnionByNameHandler())
