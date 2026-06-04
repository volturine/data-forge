from __future__ import annotations

from enum import StrEnum
from typing import Self


class DataForgeStrEnum(StrEnum):
    @classmethod
    def values(cls) -> list[str]:
        return [item.value for item in cls]

    @classmethod
    def parse(cls, value: Self | str | None) -> Self | None:
        if value is None:
            return None
        return cls(value)

    @classmethod
    def require(cls, value: Self | str) -> Self:
        return cls(value)

    @classmethod
    def read(cls, value: object, *, default: Self | None = None) -> Self | None:
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            try:
                return cls(value)
            except ValueError:
                if default is not None:
                    return default
        elif value is None:
            return default
        if default is not None:
            return default
        raise ValueError(f'Unsupported {cls.__name__}: {value!r}')
