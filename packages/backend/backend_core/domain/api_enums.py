from __future__ import annotations

from typing import Any, ClassVar, Self, cast

from pydantic_core import core_schema

from dataforge_protocol import enums_pb2


def _api_token(proto_enum: str, number: int) -> str:
    enum_descriptor = enums_pb2.DESCRIPTOR.enum_types_by_name[proto_enum]
    value_descriptor = enum_descriptor.values_by_number[number]
    return cast(str, value_descriptor.GetOptions().Extensions[cast(Any, enums_pb2.dataforge_token)])


class ApiEnumValue(str):
    """A str-valued enum whose members are the dataforge_token options of a protobuf enum.

    The protobuf enum defaults to the subclass name; pass ``proto_enum`` when they differ.
    """

    _proto_enum: ClassVar[str]
    _number_by_token: ClassVar[dict[str, int]]
    _value_by_number: ClassVar[dict[int, Self]]
    _value_by_token: ClassVar[dict[str, Self]]

    def __init_subclass__(cls, *, proto_enum: str | None = None) -> None:
        cls._proto_enum = proto_enum or cls.__name__
        cls._number_by_token = {}
        cls._value_by_number = {}
        cls._value_by_token = {}

    def __new__(cls, number: int) -> Self:
        token = _api_token(cls._proto_enum, number)
        value = cast(Self, str.__new__(cls, token))
        cls._number_by_token[token] = number
        cls._value_by_number[number] = value
        cls._value_by_token[token] = value
        return value

    @property
    def value(self) -> str:
        return str.__str__(self)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, str):
            return False
        return str.__eq__(self, other)

    def __hash__(self) -> int:
        return str.__hash__(self)

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
        raise ValueError(f'Unsupported {cls.__name__}: {value!r}')

    @classmethod
    def read(cls, value: object, *, default: Self | None = None) -> Self | None:
        try:
            return cls.require(cast(Self | str | int, value))
        except ValueError:
            if value is None or default is not None:
                return default
            raise

    def __reduce__(self) -> tuple[object, tuple[str]]:
        return (type(self).require, (str(self),))

    @staticmethod
    def _serialize(value: ApiEnumValue, info: core_schema.SerializationInfo) -> str | int:
        if info.context is not None and info.context.get('protocol_enum_numbers') is True:
            return value.number
        return value.value

    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: object,
        _handler: object,
    ) -> core_schema.CoreSchema:
        return core_schema.no_info_plain_validator_function(
            cls.require,
            serialization=core_schema.plain_serializer_function_ser_schema(cls._serialize, info_arg=True),
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        _core_schema: core_schema.CoreSchema,
        _handler: object,
    ) -> dict[str, object]:
        return {'type': 'string', 'enum': cls.values()}
