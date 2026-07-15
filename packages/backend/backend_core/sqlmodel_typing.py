from typing import Any, cast

from sqlmodel import col as sqlmodel_col


def col[T](value: T) -> Any:
    return sqlmodel_col(cast(Any, value))


def sa[T](value: T) -> Any:
    return value
