"""View passthrough operation."""

from modules.compute.operations.base import OperationParams, make_handler


class ViewParams(OperationParams):
    rowLimit: int | None = None


ViewHandler = make_handler('view', ViewParams, lambda lf, _: lf)
