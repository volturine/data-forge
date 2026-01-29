"""Null count profiling operation."""

import polars as pl

from modules.compute.operations.base import OperationParams, make_handler


class NullCountParams(OperationParams):
    pass


NullCountHandler = make_handler('null_count', NullCountParams, lambda lf, _: lf.select(pl.all().null_count()))
