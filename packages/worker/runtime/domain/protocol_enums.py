from __future__ import annotations

from typing import Any, ClassVar, Self, cast

from pydantic_core import core_schema

from dataforge_protocol import enums_pb2


def protocol_token(enum_name: str, number: int) -> str:
    enum_descriptor = enums_pb2.DESCRIPTOR.enum_types_by_name[enum_name]
    value_descriptor = enum_descriptor.values_by_number[number]
    return cast(str, value_descriptor.GetOptions().Extensions[cast(Any, enums_pb2.dataforge_token)])


class ProtocolEnumValue(str):
    _token_by_number: ClassVar[dict[int, str]]
    _number_by_token: ClassVar[dict[str, int]]
    _value_by_number: ClassVar[dict[int, Self]]
    _value_by_token: ClassVar[dict[str, Self]]

    def __init_subclass__(cls) -> None:
        cls._token_by_number = {}
        cls._number_by_token = {}
        cls._value_by_number = {}
        cls._value_by_token = {}

    def __new__(cls, number: int, token: str) -> Self:
        value = cast(Self, str.__new__(cls, token))
        cls._token_by_number[number] = token
        cls._number_by_token[token] = number
        cls._value_by_number[number] = value
        cls._value_by_token[token] = value
        return value

    @property
    def value(self) -> str:
        return str.__str__(self)

    @property
    def number(self) -> int:
        return type(self)._number_by_token[str.__str__(self)]

    @classmethod
    def values(cls) -> list[str]:
        return list(cls._value_by_token)

    @classmethod
    def members(cls) -> list[Self]:
        return list(cls._value_by_token.values())

    @classmethod
    def parse(cls, value: Self | str | int | None) -> Self | None:
        if value is None:
            return None
        return cls.require(value)

    @classmethod
    def require(cls, value: Self | str | int) -> Self:
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            try:
                return cls._value_by_token[value]
            except KeyError:
                pass
        if isinstance(value, int):
            try:
                return cls._value_by_number[value]
            except KeyError:
                pass
        raise ValueError(f"Unsupported {cls.__name__}: {value!r}")

    @classmethod
    def read(cls, value: object, *, default: Self | None = None) -> Self | None:
        try:
            return cls.require(cast(Self | str | int, value))
        except ValueError:
            if value is None or default is not None:
                return default
            raise

    def __str__(self) -> str:
        return str.__str__(self)

    def __reduce__(self) -> tuple[object, tuple[str]]:
        return (type(self).require, (str(self),))

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: object,
        _handler: object,
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_plain_validator_function(
            cls.require,
            serialization=core_schema.plain_serializer_function_ser_schema(lambda value: value.value, when_used="json"),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        _core_schema: core_schema.CoreSchema,
        _handler: object,
    ) -> dict[str, object]:
        return {"type": "string", "enum": cls.values()}
