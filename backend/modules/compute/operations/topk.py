"""Top-K rows operation."""

from modules.compute.operations.base import OperationParams, make_handler


class TopKParams(OperationParams):
    column: str
    k: int = 10
    descending: bool = False


TopKHandler = make_handler('topk', TopKParams, lambda lf, p: lf.sort(p.column, descending=p.descending).head(p.k))
