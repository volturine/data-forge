from __future__ import annotations

from enum import StrEnum
from typing import Self


class DataForgeStrEnum(StrEnum):
    @classmethod
    def values(cls) -> list[str]:
        return [item.value for item in cls]

    @classmethod
    def require(cls, value: Self | str) -> Self:
        return cls(value)
