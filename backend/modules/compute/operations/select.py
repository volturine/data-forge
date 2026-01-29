"""Select columns operation."""

from modules.compute.operations.base import OperationParams, make_handler


class SelectParams(OperationParams):
    columns: list[str]


SelectHandler = make_handler('select', SelectParams, lambda lf, p: lf.select(p.columns))
