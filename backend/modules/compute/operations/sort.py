"""Sort rows operation."""

from modules.compute.operations.base import OperationParams, make_handler


class SortParams(OperationParams):
    columns: list[str]
    descending: list[bool] | bool = False


SortHandler = make_handler('sort', SortParams, lambda lf, p: lf.sort(p.columns, descending=p.descending))
