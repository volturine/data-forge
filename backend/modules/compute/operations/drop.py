"""Drop columns operation."""

from modules.compute.operations.base import OperationParams, make_handler


class DropParams(OperationParams):
    columns: list[str]


DropHandler = make_handler('drop', DropParams, lambda lf, p: lf.drop(p.columns))
