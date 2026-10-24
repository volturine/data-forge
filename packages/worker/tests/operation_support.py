import polars as pl

from operations import OPERATIONS


def run_operation(name: str, lf: pl.LazyFrame, params: dict[str, object], *, step_id: str = "test", **kwargs: object) -> pl.LazyFrame:
    operation = OPERATIONS[name]
    return operation.apply(lf, operation.params.model_validate(params), step_id=step_id, **kwargs)
