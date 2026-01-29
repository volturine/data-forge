from collections.abc import Callable
from typing import Protocol, TypeVar, runtime_checkable

import polars as pl
from pydantic import BaseModel, ConfigDict


class OperationParams(BaseModel):
    model_config = ConfigDict(extra='forbid')


@runtime_checkable
class OperationHandler(Protocol):
    @property
    def name(self) -> str: ...

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame: ...


P = TypeVar('P', bound=OperationParams)


class _Handler:
    """Concrete handler instance created by make_handler."""

    def __init__(self, name: str, params_cls: type[OperationParams], fn: Callable[[pl.LazyFrame, OperationParams], pl.LazyFrame]) -> None:
        self._name = name
        self._params_cls = params_cls
        self._fn = fn

    @property
    def name(self) -> str:
        return self._name

    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        right_sources: dict[str, pl.LazyFrame] | None = None,
    ) -> pl.LazyFrame:
        validated = self._params_cls.model_validate(params)
        return self._fn(lf, validated)


def make_handler(
    name: str,
    params_cls: type[P],
    fn: Callable[[pl.LazyFrame, P], pl.LazyFrame],
) -> _Handler:
    """Create a handler from a params class and transform function."""
    return _Handler(name, params_cls, fn)  # type: ignore[arg-type]
