from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar, Literal, Self, cast
from zoneinfo import ZoneInfo

from backend_core.domain.protocol_enums import ProtocolEnumValue, protocol_token
from dataforge_protocol import enums_pb2


class FilterValueType(ProtocolEnumValue):
    STRING: ClassVar[Self]
    NUMBER: ClassVar[Self]
    DATE: ClassVar[Self]
    DATETIME: ClassVar[Self]
    COLUMN: ClassVar[Self]
    BOOLEAN: ClassVar[Self]

    @staticmethod
    def parse_datetime(value: str) -> datetime:
        if value.endswith('Z'):
            value = value[:-1] + '+00:00'
        if ' ' in value and 'T' not in value:
            raise ValueError(
                f"Cannot parse datetime string '{value}'. Accepted format: ISO 8601 (for example 2024-06-15T12:30:00)",
            )
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            raise ValueError(
                f"Cannot parse datetime string '{value}'. Accepted format: ISO 8601 (for example 2024-06-15T12:30:00)",
            ) from None

    def coerce(self, value: Any, *, normalize_tz: bool = False, timezone: str = 'UTC') -> Any:
        if value is None:
            return None

        if isinstance(value, list):
            return [self.coerce(item, normalize_tz=normalize_tz, timezone=timezone) for item in value]

        if self == FilterValueType.NUMBER:
            if isinstance(value, (int, float)):
                return value
            text = str(value)
            parsed = float(text)
            if parsed.is_integer() and '.' not in text and 'e' not in text.lower():
                return int(parsed)
            return parsed

        if self == FilterValueType.BOOLEAN:
            if isinstance(value, bool):
                return value
            return str(value).lower() in ('true', '1', 'yes')

        if self == FilterValueType.DATE:
            if isinstance(value, datetime):
                return value.date()
            return self.parse_datetime(str(value)).date()

        if self == FilterValueType.DATETIME:
            parsed_dt = value if isinstance(value, datetime) else self.parse_datetime(str(value))
            if not parsed_dt.tzinfo and not normalize_tz:
                return parsed_dt
            tz = ZoneInfo(timezone)
            parsed_dt = parsed_dt.replace(tzinfo=tz) if not parsed_dt.tzinfo else parsed_dt.astimezone(tz)
            return parsed_dt if normalize_tz else parsed_dt.replace(tzinfo=None)

        return str(value)


FilterValueType.STRING = FilterValueType(enums_pb2.FILTER_VALUE_TYPE_STRING, protocol_token('FilterValueType', enums_pb2.FILTER_VALUE_TYPE_STRING))
FilterValueType.NUMBER = FilterValueType(enums_pb2.FILTER_VALUE_TYPE_NUMBER, protocol_token('FilterValueType', enums_pb2.FILTER_VALUE_TYPE_NUMBER))
FilterValueType.DATE = FilterValueType(enums_pb2.FILTER_VALUE_TYPE_DATE, protocol_token('FilterValueType', enums_pb2.FILTER_VALUE_TYPE_DATE))
FilterValueType.DATETIME = FilterValueType(enums_pb2.FILTER_VALUE_TYPE_DATETIME, protocol_token('FilterValueType', enums_pb2.FILTER_VALUE_TYPE_DATETIME))
FilterValueType.COLUMN = FilterValueType(enums_pb2.FILTER_VALUE_TYPE_COLUMN, protocol_token('FilterValueType', enums_pb2.FILTER_VALUE_TYPE_COLUMN))
FilterValueType.BOOLEAN = FilterValueType(enums_pb2.FILTER_VALUE_TYPE_BOOLEAN, protocol_token('FilterValueType', enums_pb2.FILTER_VALUE_TYPE_BOOLEAN))


class FilterLogic(ProtocolEnumValue):
    AND: ClassVar[Self]
    OR: ClassVar[Self]

    @property
    def expression_combiner(self) -> str:
        return 'all' if self == FilterLogic.AND else 'any'


FilterLogic.AND = FilterLogic(enums_pb2.FILTER_LOGIC_AND, protocol_token('FilterLogic', enums_pb2.FILTER_LOGIC_AND))
FilterLogic.OR = FilterLogic(enums_pb2.FILTER_LOGIC_OR, protocol_token('FilterLogic', enums_pb2.FILTER_LOGIC_OR))


class FilterOperator(ProtocolEnumValue):
    EQUAL: ClassVar[Self]
    DOUBLE_EQUAL: ClassVar[Self]
    NOT_EQUAL: ClassVar[Self]
    GREATER_THAN: ClassVar[Self]
    LESS_THAN: ClassVar[Self]
    GREATER_EQUAL: ClassVar[Self]
    LESS_EQUAL: ClassVar[Self]
    CONTAINS: ClassVar[Self]
    NOT_CONTAINS: ClassVar[Self]
    STARTS_WITH: ClassVar[Self]
    ENDS_WITH: ClassVar[Self]
    REGEX: ClassVar[Self]
    IS_NULL: ClassVar[Self]
    IS_NOT_NULL: ClassVar[Self]
    IN: ClassVar[Self]
    NOT_IN: ClassVar[Self]

    @classmethod
    def unsupported_message(cls, value: object) -> str:
        return f'Unsupported filter operator: {value}'

    @classmethod
    def require_supported(cls, value: object) -> FilterOperator:
        try:
            return cls.require(cast(FilterOperator | str | int, value))
        except ValueError as exc:
            raise ValueError(cls.unsupported_message(value)) from exc

    @property
    def is_null_check(self) -> bool:
        return self in {FilterOperator.IS_NULL, FilterOperator.IS_NOT_NULL}

    @property
    def supports_column_comparison(self) -> bool:
        return self in {
            FilterOperator.EQUAL,
            FilterOperator.DOUBLE_EQUAL,
            FilterOperator.NOT_EQUAL,
            FilterOperator.GREATER_THAN,
            FilterOperator.LESS_THAN,
            FilterOperator.GREATER_EQUAL,
            FilterOperator.LESS_EQUAL,
        }

    @property
    def is_membership(self) -> bool:
        return self in {FilterOperator.IN, FilterOperator.NOT_IN}

    @property
    def empty_list_result(self) -> bool:
        return self in {FilterOperator.NOT_CONTAINS, FilterOperator.NOT_IN}

    @property
    def folds_list_with_all(self) -> bool:
        return self == FilterOperator.NOT_CONTAINS

    @property
    def requires_regex_validation(self) -> bool:
        return self == FilterOperator.REGEX

    @property
    def empty_string_result(self) -> bool | None:
        if self == FilterOperator.REGEX:
            return False
        return None

    @property
    def polars_binary_token(self) -> str | None:
        if self == FilterOperator.EQUAL:
            return '=='
        if self.supports_column_comparison:
            return self.value
        return None

    @property
    def sql_binary_token(self) -> str | None:
        if self == FilterOperator.DOUBLE_EQUAL:
            return '='
        if self.supports_column_comparison:
            return self.value
        return None


FilterOperator.EQUAL = FilterOperator(enums_pb2.FILTER_OPERATOR_EQUAL, protocol_token('FilterOperator', enums_pb2.FILTER_OPERATOR_EQUAL))
FilterOperator.DOUBLE_EQUAL = FilterOperator(enums_pb2.FILTER_OPERATOR_DOUBLE_EQUAL, protocol_token('FilterOperator', enums_pb2.FILTER_OPERATOR_DOUBLE_EQUAL))
FilterOperator.NOT_EQUAL = FilterOperator(enums_pb2.FILTER_OPERATOR_NOT_EQUAL, protocol_token('FilterOperator', enums_pb2.FILTER_OPERATOR_NOT_EQUAL))
FilterOperator.GREATER_THAN = FilterOperator(enums_pb2.FILTER_OPERATOR_GREATER_THAN, protocol_token('FilterOperator', enums_pb2.FILTER_OPERATOR_GREATER_THAN))
FilterOperator.LESS_THAN = FilterOperator(enums_pb2.FILTER_OPERATOR_LESS_THAN, protocol_token('FilterOperator', enums_pb2.FILTER_OPERATOR_LESS_THAN))
FilterOperator.GREATER_EQUAL = FilterOperator(
    enums_pb2.FILTER_OPERATOR_GREATER_EQUAL, protocol_token('FilterOperator', enums_pb2.FILTER_OPERATOR_GREATER_EQUAL)
)
FilterOperator.LESS_EQUAL = FilterOperator(enums_pb2.FILTER_OPERATOR_LESS_EQUAL, protocol_token('FilterOperator', enums_pb2.FILTER_OPERATOR_LESS_EQUAL))
FilterOperator.CONTAINS = FilterOperator(enums_pb2.FILTER_OPERATOR_CONTAINS, protocol_token('FilterOperator', enums_pb2.FILTER_OPERATOR_CONTAINS))
FilterOperator.NOT_CONTAINS = FilterOperator(enums_pb2.FILTER_OPERATOR_NOT_CONTAINS, protocol_token('FilterOperator', enums_pb2.FILTER_OPERATOR_NOT_CONTAINS))
FilterOperator.STARTS_WITH = FilterOperator(enums_pb2.FILTER_OPERATOR_STARTS_WITH, protocol_token('FilterOperator', enums_pb2.FILTER_OPERATOR_STARTS_WITH))
FilterOperator.ENDS_WITH = FilterOperator(enums_pb2.FILTER_OPERATOR_ENDS_WITH, protocol_token('FilterOperator', enums_pb2.FILTER_OPERATOR_ENDS_WITH))
FilterOperator.REGEX = FilterOperator(enums_pb2.FILTER_OPERATOR_REGEX, protocol_token('FilterOperator', enums_pb2.FILTER_OPERATOR_REGEX))
FilterOperator.IS_NULL = FilterOperator(enums_pb2.FILTER_OPERATOR_IS_NULL, protocol_token('FilterOperator', enums_pb2.FILTER_OPERATOR_IS_NULL))
FilterOperator.IS_NOT_NULL = FilterOperator(enums_pb2.FILTER_OPERATOR_IS_NOT_NULL, protocol_token('FilterOperator', enums_pb2.FILTER_OPERATOR_IS_NOT_NULL))
FilterOperator.IN = FilterOperator(enums_pb2.FILTER_OPERATOR_IN, protocol_token('FilterOperator', enums_pb2.FILTER_OPERATOR_IN))
FilterOperator.NOT_IN = FilterOperator(enums_pb2.FILTER_OPERATOR_NOT_IN, protocol_token('FilterOperator', enums_pb2.FILTER_OPERATOR_NOT_IN))


class StringTransformMethod(ProtocolEnumValue):
    UPPERCASE: ClassVar[Self]
    LOWERCASE: ClassVar[Self]
    TITLE: ClassVar[Self]
    STRIP: ClassVar[Self]
    LSTRIP: ClassVar[Self]
    RSTRIP: ClassVar[Self]
    LENGTH: ClassVar[Self]
    SLICE: ClassVar[Self]
    REPLACE: ClassVar[Self]
    EXTRACT: ClassVar[Self]
    SPLIT: ClassVar[Self]
    SPLIT_TAKE: ClassVar[Self]


StringTransformMethod.UPPERCASE = StringTransformMethod(
    enums_pb2.STRING_TRANSFORM_METHOD_UPPERCASE, protocol_token('StringTransformMethod', enums_pb2.STRING_TRANSFORM_METHOD_UPPERCASE)
)
StringTransformMethod.LOWERCASE = StringTransformMethod(
    enums_pb2.STRING_TRANSFORM_METHOD_LOWERCASE, protocol_token('StringTransformMethod', enums_pb2.STRING_TRANSFORM_METHOD_LOWERCASE)
)
StringTransformMethod.TITLE = StringTransformMethod(
    enums_pb2.STRING_TRANSFORM_METHOD_TITLE, protocol_token('StringTransformMethod', enums_pb2.STRING_TRANSFORM_METHOD_TITLE)
)
StringTransformMethod.STRIP = StringTransformMethod(
    enums_pb2.STRING_TRANSFORM_METHOD_STRIP, protocol_token('StringTransformMethod', enums_pb2.STRING_TRANSFORM_METHOD_STRIP)
)
StringTransformMethod.LSTRIP = StringTransformMethod(
    enums_pb2.STRING_TRANSFORM_METHOD_LSTRIP, protocol_token('StringTransformMethod', enums_pb2.STRING_TRANSFORM_METHOD_LSTRIP)
)
StringTransformMethod.RSTRIP = StringTransformMethod(
    enums_pb2.STRING_TRANSFORM_METHOD_RSTRIP, protocol_token('StringTransformMethod', enums_pb2.STRING_TRANSFORM_METHOD_RSTRIP)
)
StringTransformMethod.LENGTH = StringTransformMethod(
    enums_pb2.STRING_TRANSFORM_METHOD_LENGTH, protocol_token('StringTransformMethod', enums_pb2.STRING_TRANSFORM_METHOD_LENGTH)
)
StringTransformMethod.SLICE = StringTransformMethod(
    enums_pb2.STRING_TRANSFORM_METHOD_SLICE, protocol_token('StringTransformMethod', enums_pb2.STRING_TRANSFORM_METHOD_SLICE)
)
StringTransformMethod.REPLACE = StringTransformMethod(
    enums_pb2.STRING_TRANSFORM_METHOD_REPLACE, protocol_token('StringTransformMethod', enums_pb2.STRING_TRANSFORM_METHOD_REPLACE)
)
StringTransformMethod.EXTRACT = StringTransformMethod(
    enums_pb2.STRING_TRANSFORM_METHOD_EXTRACT, protocol_token('StringTransformMethod', enums_pb2.STRING_TRANSFORM_METHOD_EXTRACT)
)
StringTransformMethod.SPLIT = StringTransformMethod(
    enums_pb2.STRING_TRANSFORM_METHOD_SPLIT, protocol_token('StringTransformMethod', enums_pb2.STRING_TRANSFORM_METHOD_SPLIT)
)
StringTransformMethod.SPLIT_TAKE = StringTransformMethod(
    enums_pb2.STRING_TRANSFORM_METHOD_SPLIT_TAKE, protocol_token('StringTransformMethod', enums_pb2.STRING_TRANSFORM_METHOD_SPLIT_TAKE)
)


class TimeseriesOperationType(ProtocolEnumValue):
    EXTRACT: ClassVar[Self]
    TIMESTAMP: ClassVar[Self]
    ADD: ClassVar[Self]
    SUBTRACT: ClassVar[Self]
    OFFSET: ClassVar[Self]
    DIFF: ClassVar[Self]
    TRUNCATE: ClassVar[Self]
    ROUND: ClassVar[Self]


TimeseriesOperationType.EXTRACT = TimeseriesOperationType(
    enums_pb2.TIMESERIES_OPERATION_TYPE_EXTRACT, protocol_token('TimeseriesOperationType', enums_pb2.TIMESERIES_OPERATION_TYPE_EXTRACT)
)
TimeseriesOperationType.TIMESTAMP = TimeseriesOperationType(
    enums_pb2.TIMESERIES_OPERATION_TYPE_TIMESTAMP, protocol_token('TimeseriesOperationType', enums_pb2.TIMESERIES_OPERATION_TYPE_TIMESTAMP)
)
TimeseriesOperationType.ADD = TimeseriesOperationType(
    enums_pb2.TIMESERIES_OPERATION_TYPE_ADD, protocol_token('TimeseriesOperationType', enums_pb2.TIMESERIES_OPERATION_TYPE_ADD)
)
TimeseriesOperationType.SUBTRACT = TimeseriesOperationType(
    enums_pb2.TIMESERIES_OPERATION_TYPE_SUBTRACT, protocol_token('TimeseriesOperationType', enums_pb2.TIMESERIES_OPERATION_TYPE_SUBTRACT)
)
TimeseriesOperationType.OFFSET = TimeseriesOperationType(
    enums_pb2.TIMESERIES_OPERATION_TYPE_OFFSET, protocol_token('TimeseriesOperationType', enums_pb2.TIMESERIES_OPERATION_TYPE_OFFSET)
)
TimeseriesOperationType.DIFF = TimeseriesOperationType(
    enums_pb2.TIMESERIES_OPERATION_TYPE_DIFF, protocol_token('TimeseriesOperationType', enums_pb2.TIMESERIES_OPERATION_TYPE_DIFF)
)
TimeseriesOperationType.TRUNCATE = TimeseriesOperationType(
    enums_pb2.TIMESERIES_OPERATION_TYPE_TRUNCATE, protocol_token('TimeseriesOperationType', enums_pb2.TIMESERIES_OPERATION_TYPE_TRUNCATE)
)
TimeseriesOperationType.ROUND = TimeseriesOperationType(
    enums_pb2.TIMESERIES_OPERATION_TYPE_ROUND, protocol_token('TimeseriesOperationType', enums_pb2.TIMESERIES_OPERATION_TYPE_ROUND)
)


class TimeComponent(ProtocolEnumValue):
    YEAR: ClassVar[Self]
    MONTH: ClassVar[Self]
    DAY: ClassVar[Self]
    HOUR: ClassVar[Self]
    MINUTE: ClassVar[Self]
    SECOND: ClassVar[Self]
    QUARTER: ClassVar[Self]
    WEEK: ClassVar[Self]
    DAYOFWEEK: ClassVar[Self]

    @property
    def extractor_name(self) -> str:
        if self == TimeComponent.DAYOFWEEK:
            return 'weekday'
        return self.value


TimeComponent.YEAR = TimeComponent(enums_pb2.TIME_COMPONENT_YEAR, protocol_token('TimeComponent', enums_pb2.TIME_COMPONENT_YEAR))
TimeComponent.MONTH = TimeComponent(enums_pb2.TIME_COMPONENT_MONTH, protocol_token('TimeComponent', enums_pb2.TIME_COMPONENT_MONTH))
TimeComponent.DAY = TimeComponent(enums_pb2.TIME_COMPONENT_DAY, protocol_token('TimeComponent', enums_pb2.TIME_COMPONENT_DAY))
TimeComponent.HOUR = TimeComponent(enums_pb2.TIME_COMPONENT_HOUR, protocol_token('TimeComponent', enums_pb2.TIME_COMPONENT_HOUR))
TimeComponent.MINUTE = TimeComponent(enums_pb2.TIME_COMPONENT_MINUTE, protocol_token('TimeComponent', enums_pb2.TIME_COMPONENT_MINUTE))
TimeComponent.SECOND = TimeComponent(enums_pb2.TIME_COMPONENT_SECOND, protocol_token('TimeComponent', enums_pb2.TIME_COMPONENT_SECOND))
TimeComponent.QUARTER = TimeComponent(enums_pb2.TIME_COMPONENT_QUARTER, protocol_token('TimeComponent', enums_pb2.TIME_COMPONENT_QUARTER))
TimeComponent.WEEK = TimeComponent(enums_pb2.TIME_COMPONENT_WEEK, protocol_token('TimeComponent', enums_pb2.TIME_COMPONENT_WEEK))
TimeComponent.DAYOFWEEK = TimeComponent(enums_pb2.TIME_COMPONENT_DAYOFWEEK, protocol_token('TimeComponent', enums_pb2.TIME_COMPONENT_DAYOFWEEK))


class DurationUnit(ProtocolEnumValue):
    SECONDS: ClassVar[Self]
    MINUTES: ClassVar[Self]
    HOURS: ClassVar[Self]
    DAYS: ClassVar[Self]
    WEEKS: ClassVar[Self]
    MONTHS: ClassVar[Self]

    @property
    def every_token(self) -> str:
        match self:
            case DurationUnit.SECONDS:
                return '1s'
            case DurationUnit.MINUTES:
                return '1m'
            case DurationUnit.HOURS:
                return '1h'
            case DurationUnit.DAYS:
                return '1d'
            case DurationUnit.WEEKS:
                return '1w'
            case DurationUnit.MONTHS:
                return '1mo'
        raise ValueError(f'Unsupported duration unit: {self.value}')


DurationUnit.SECONDS = DurationUnit(enums_pb2.DURATION_UNIT_SECONDS, protocol_token('DurationUnit', enums_pb2.DURATION_UNIT_SECONDS))
DurationUnit.MINUTES = DurationUnit(enums_pb2.DURATION_UNIT_MINUTES, protocol_token('DurationUnit', enums_pb2.DURATION_UNIT_MINUTES))
DurationUnit.HOURS = DurationUnit(enums_pb2.DURATION_UNIT_HOURS, protocol_token('DurationUnit', enums_pb2.DURATION_UNIT_HOURS))
DurationUnit.DAYS = DurationUnit(enums_pb2.DURATION_UNIT_DAYS, protocol_token('DurationUnit', enums_pb2.DURATION_UNIT_DAYS))
DurationUnit.WEEKS = DurationUnit(enums_pb2.DURATION_UNIT_WEEKS, protocol_token('DurationUnit', enums_pb2.DURATION_UNIT_WEEKS))
DurationUnit.MONTHS = DurationUnit(enums_pb2.DURATION_UNIT_MONTHS, protocol_token('DurationUnit', enums_pb2.DURATION_UNIT_MONTHS))


class TimeDirection(ProtocolEnumValue):
    ADD: ClassVar[Self]
    SUBTRACT: ClassVar[Self]


TimeDirection.ADD = TimeDirection(enums_pb2.TIME_DIRECTION_ADD, protocol_token('TimeDirection', enums_pb2.TIME_DIRECTION_ADD))
TimeDirection.SUBTRACT = TimeDirection(enums_pb2.TIME_DIRECTION_SUBTRACT, protocol_token('TimeDirection', enums_pb2.TIME_DIRECTION_SUBTRACT))


class WithColumnsExprType(ProtocolEnumValue):
    LITERAL: ClassVar[Self]
    COLUMN: ClassVar[Self]
    UDF: ClassVar[Self]


WithColumnsExprType.LITERAL = WithColumnsExprType(
    enums_pb2.WITH_COLUMNS_EXPR_TYPE_LITERAL, protocol_token('WithColumnsExprType', enums_pb2.WITH_COLUMNS_EXPR_TYPE_LITERAL)
)
WithColumnsExprType.COLUMN = WithColumnsExprType(
    enums_pb2.WITH_COLUMNS_EXPR_TYPE_COLUMN, protocol_token('WithColumnsExprType', enums_pb2.WITH_COLUMNS_EXPR_TYPE_COLUMN)
)
WithColumnsExprType.UDF = WithColumnsExprType(enums_pb2.WITH_COLUMNS_EXPR_TYPE_UDF, protocol_token('WithColumnsExprType', enums_pb2.WITH_COLUMNS_EXPR_TYPE_UDF))


class NotificationMethod(ProtocolEnumValue):
    EMAIL: ClassVar[Self]
    TELEGRAM: ClassVar[Self]


NotificationMethod.EMAIL = NotificationMethod(enums_pb2.NOTIFICATION_METHOD_EMAIL, protocol_token('NotificationMethod', enums_pb2.NOTIFICATION_METHOD_EMAIL))
NotificationMethod.TELEGRAM = NotificationMethod(
    enums_pb2.NOTIFICATION_METHOD_TELEGRAM, protocol_token('NotificationMethod', enums_pb2.NOTIFICATION_METHOD_TELEGRAM)
)


class JoinHow(ProtocolEnumValue):
    INNER: ClassVar[Self]
    LEFT: ClassVar[Self]
    RIGHT: ClassVar[Self]
    OUTER: ClassVar[Self]
    CROSS: ClassVar[Self]

    @property
    def polars_how(self) -> Literal['inner', 'left', 'right', 'full', 'cross']:
        if self == JoinHow.OUTER:
            return 'full'
        return cast(Literal['inner', 'left', 'right', 'cross'], self.value)

    @property
    def sql_join_type(self) -> Literal['INNER JOIN', 'LEFT JOIN', 'RIGHT JOIN', 'FULL OUTER JOIN', 'CROSS JOIN']:
        if self == JoinHow.OUTER:
            return 'FULL OUTER JOIN'
        return cast(Literal['INNER JOIN', 'LEFT JOIN', 'RIGHT JOIN', 'CROSS JOIN'], f'{self.value.upper()} JOIN')

    @property
    def requires_join_keys(self) -> bool:
        return self != JoinHow.CROSS


JoinHow.INNER = JoinHow(enums_pb2.JOIN_HOW_INNER, protocol_token('JoinHow', enums_pb2.JOIN_HOW_INNER))
JoinHow.LEFT = JoinHow(enums_pb2.JOIN_HOW_LEFT, protocol_token('JoinHow', enums_pb2.JOIN_HOW_LEFT))
JoinHow.RIGHT = JoinHow(enums_pb2.JOIN_HOW_RIGHT, protocol_token('JoinHow', enums_pb2.JOIN_HOW_RIGHT))
JoinHow.OUTER = JoinHow(enums_pb2.JOIN_HOW_OUTER, protocol_token('JoinHow', enums_pb2.JOIN_HOW_OUTER))
JoinHow.CROSS = JoinHow(enums_pb2.JOIN_HOW_CROSS, protocol_token('JoinHow', enums_pb2.JOIN_HOW_CROSS))


class GroupByAggregationFunction(ProtocolEnumValue):
    SUM: ClassVar[Self]
    MEAN: ClassVar[Self]
    COUNT: ClassVar[Self]
    MIN: ClassVar[Self]
    MAX: ClassVar[Self]
    FIRST: ClassVar[Self]
    LAST: ClassVar[Self]
    MEDIAN: ClassVar[Self]
    STD: ClassVar[Self]
    N_UNIQUE: ClassVar[Self]
    COLLECT_LIST: ClassVar[Self]
    COLLECT_SET: ClassVar[Self]

    def default_alias(self, column: str) -> str:
        return f'{column}_{self.value}'

    def render_polars_export(self, column_expr: str, alias_expr: str) -> str:
        match self:
            case GroupByAggregationFunction.COLLECT_LIST:
                return f'{column_expr}.implode().alias({alias_expr})'
            case GroupByAggregationFunction.COLLECT_SET:
                return f'{column_expr}.implode().list.unique().alias({alias_expr})'
            case _:
                return f'{column_expr}.{self.polars_method_name}().alias({alias_expr})'

    def render_sql_export(self, column_expr: str, alias_expr: str) -> str | None:
        match self:
            case GroupByAggregationFunction.MEDIAN:
                return f'PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {column_expr}) AS {alias_expr}'
            case GroupByAggregationFunction.N_UNIQUE:
                return f'COUNT(DISTINCT {column_expr}) AS {alias_expr}'
            case GroupByAggregationFunction.COLLECT_LIST:
                return f'ARRAY_AGG({column_expr}) AS {alias_expr}'
            case GroupByAggregationFunction.COLLECT_SET:
                return f'ARRAY_AGG(DISTINCT {column_expr}) AS {alias_expr}'
            case _:
                if (sql_function := self.sql_function_name) is None:
                    return None
                return f'{sql_function}({column_expr}) AS {alias_expr}'

    @property
    def polars_method_name(self) -> str:
        match self:
            case GroupByAggregationFunction.COLLECT_LIST | GroupByAggregationFunction.COLLECT_SET:
                raise ValueError(f'GroupBy aggregation {self.value} does not define a Polars method name')
            case _:
                return self.value

    @property
    def sql_function_name(self) -> str | None:
        match self:
            case GroupByAggregationFunction.MEAN:
                return 'AVG'
            case GroupByAggregationFunction.STD:
                return 'STDDEV_POP'
            case GroupByAggregationFunction.SUM | GroupByAggregationFunction.COUNT | GroupByAggregationFunction.MIN | GroupByAggregationFunction.MAX:
                return self.value.upper()
            case _:
                return None


GroupByAggregationFunction.SUM = GroupByAggregationFunction(
    enums_pb2.GROUP_BY_AGGREGATION_FUNCTION_SUM, protocol_token('GroupByAggregationFunction', enums_pb2.GROUP_BY_AGGREGATION_FUNCTION_SUM)
)
GroupByAggregationFunction.MEAN = GroupByAggregationFunction(
    enums_pb2.GROUP_BY_AGGREGATION_FUNCTION_MEAN, protocol_token('GroupByAggregationFunction', enums_pb2.GROUP_BY_AGGREGATION_FUNCTION_MEAN)
)
GroupByAggregationFunction.COUNT = GroupByAggregationFunction(
    enums_pb2.GROUP_BY_AGGREGATION_FUNCTION_COUNT, protocol_token('GroupByAggregationFunction', enums_pb2.GROUP_BY_AGGREGATION_FUNCTION_COUNT)
)
GroupByAggregationFunction.MIN = GroupByAggregationFunction(
    enums_pb2.GROUP_BY_AGGREGATION_FUNCTION_MIN, protocol_token('GroupByAggregationFunction', enums_pb2.GROUP_BY_AGGREGATION_FUNCTION_MIN)
)
GroupByAggregationFunction.MAX = GroupByAggregationFunction(
    enums_pb2.GROUP_BY_AGGREGATION_FUNCTION_MAX, protocol_token('GroupByAggregationFunction', enums_pb2.GROUP_BY_AGGREGATION_FUNCTION_MAX)
)
GroupByAggregationFunction.FIRST = GroupByAggregationFunction(
    enums_pb2.GROUP_BY_AGGREGATION_FUNCTION_FIRST, protocol_token('GroupByAggregationFunction', enums_pb2.GROUP_BY_AGGREGATION_FUNCTION_FIRST)
)
GroupByAggregationFunction.LAST = GroupByAggregationFunction(
    enums_pb2.GROUP_BY_AGGREGATION_FUNCTION_LAST, protocol_token('GroupByAggregationFunction', enums_pb2.GROUP_BY_AGGREGATION_FUNCTION_LAST)
)
GroupByAggregationFunction.MEDIAN = GroupByAggregationFunction(
    enums_pb2.GROUP_BY_AGGREGATION_FUNCTION_MEDIAN, protocol_token('GroupByAggregationFunction', enums_pb2.GROUP_BY_AGGREGATION_FUNCTION_MEDIAN)
)
GroupByAggregationFunction.STD = GroupByAggregationFunction(
    enums_pb2.GROUP_BY_AGGREGATION_FUNCTION_STD, protocol_token('GroupByAggregationFunction', enums_pb2.GROUP_BY_AGGREGATION_FUNCTION_STD)
)
GroupByAggregationFunction.N_UNIQUE = GroupByAggregationFunction(
    enums_pb2.GROUP_BY_AGGREGATION_FUNCTION_N_UNIQUE, protocol_token('GroupByAggregationFunction', enums_pb2.GROUP_BY_AGGREGATION_FUNCTION_N_UNIQUE)
)
GroupByAggregationFunction.COLLECT_LIST = GroupByAggregationFunction(
    enums_pb2.GROUP_BY_AGGREGATION_FUNCTION_COLLECT_LIST, protocol_token('GroupByAggregationFunction', enums_pb2.GROUP_BY_AGGREGATION_FUNCTION_COLLECT_LIST)
)
GroupByAggregationFunction.COLLECT_SET = GroupByAggregationFunction(
    enums_pb2.GROUP_BY_AGGREGATION_FUNCTION_COLLECT_SET, protocol_token('GroupByAggregationFunction', enums_pb2.GROUP_BY_AGGREGATION_FUNCTION_COLLECT_SET)
)


class ChartAggregation(ProtocolEnumValue):
    SUM: ClassVar[Self]
    MEAN: ClassVar[Self]
    COUNT: ClassVar[Self]
    MIN: ClassVar[Self]
    MAX: ClassVar[Self]
    MEDIAN: ClassVar[Self]
    STD: ClassVar[Self]
    VARIANCE: ClassVar[Self]
    UNIQUE_COUNT: ClassVar[Self]


ChartAggregation.SUM = ChartAggregation(enums_pb2.CHART_AGGREGATION_SUM, protocol_token('ChartAggregation', enums_pb2.CHART_AGGREGATION_SUM))
ChartAggregation.MEAN = ChartAggregation(enums_pb2.CHART_AGGREGATION_MEAN, protocol_token('ChartAggregation', enums_pb2.CHART_AGGREGATION_MEAN))
ChartAggregation.COUNT = ChartAggregation(enums_pb2.CHART_AGGREGATION_COUNT, protocol_token('ChartAggregation', enums_pb2.CHART_AGGREGATION_COUNT))
ChartAggregation.MIN = ChartAggregation(enums_pb2.CHART_AGGREGATION_MIN, protocol_token('ChartAggregation', enums_pb2.CHART_AGGREGATION_MIN))
ChartAggregation.MAX = ChartAggregation(enums_pb2.CHART_AGGREGATION_MAX, protocol_token('ChartAggregation', enums_pb2.CHART_AGGREGATION_MAX))
ChartAggregation.MEDIAN = ChartAggregation(enums_pb2.CHART_AGGREGATION_MEDIAN, protocol_token('ChartAggregation', enums_pb2.CHART_AGGREGATION_MEDIAN))
ChartAggregation.STD = ChartAggregation(enums_pb2.CHART_AGGREGATION_STD, protocol_token('ChartAggregation', enums_pb2.CHART_AGGREGATION_STD))
ChartAggregation.VARIANCE = ChartAggregation(enums_pb2.CHART_AGGREGATION_VARIANCE, protocol_token('ChartAggregation', enums_pb2.CHART_AGGREGATION_VARIANCE))
ChartAggregation.UNIQUE_COUNT = ChartAggregation(
    enums_pb2.CHART_AGGREGATION_UNIQUE_COUNT, protocol_token('ChartAggregation', enums_pb2.CHART_AGGREGATION_UNIQUE_COUNT)
)


class OverlayChartType(ProtocolEnumValue):
    LINE: ClassVar[Self]
    AREA: ClassVar[Self]
    BAR: ClassVar[Self]
    SCATTER: ClassVar[Self]


OverlayChartType.LINE = OverlayChartType(enums_pb2.OVERLAY_CHART_TYPE_LINE, protocol_token('OverlayChartType', enums_pb2.OVERLAY_CHART_TYPE_LINE))
OverlayChartType.AREA = OverlayChartType(enums_pb2.OVERLAY_CHART_TYPE_AREA, protocol_token('OverlayChartType', enums_pb2.OVERLAY_CHART_TYPE_AREA))
OverlayChartType.BAR = OverlayChartType(enums_pb2.OVERLAY_CHART_TYPE_BAR, protocol_token('OverlayChartType', enums_pb2.OVERLAY_CHART_TYPE_BAR))
OverlayChartType.SCATTER = OverlayChartType(enums_pb2.OVERLAY_CHART_TYPE_SCATTER, protocol_token('OverlayChartType', enums_pb2.OVERLAY_CHART_TYPE_SCATTER))


class YAxisPosition(ProtocolEnumValue):
    LEFT: ClassVar[Self]
    RIGHT: ClassVar[Self]


YAxisPosition.LEFT = YAxisPosition(enums_pb2.Y_AXIS_POSITION_LEFT, protocol_token('YAxisPosition', enums_pb2.Y_AXIS_POSITION_LEFT))
YAxisPosition.RIGHT = YAxisPosition(enums_pb2.Y_AXIS_POSITION_RIGHT, protocol_token('YAxisPosition', enums_pb2.Y_AXIS_POSITION_RIGHT))


class ReferenceAxis(ProtocolEnumValue):
    X: ClassVar[Self]
    Y: ClassVar[Self]


ReferenceAxis.X = ReferenceAxis(enums_pb2.REFERENCE_AXIS_X, protocol_token('ReferenceAxis', enums_pb2.REFERENCE_AXIS_X))
ReferenceAxis.Y = ReferenceAxis(enums_pb2.REFERENCE_AXIS_Y, protocol_token('ReferenceAxis', enums_pb2.REFERENCE_AXIS_Y))


class SortDirection(ProtocolEnumValue):
    ASC: ClassVar[Self]
    DESC: ClassVar[Self]


SortDirection.ASC = SortDirection(enums_pb2.SORT_DIRECTION_ASC, protocol_token('SortDirection', enums_pb2.SORT_DIRECTION_ASC))
SortDirection.DESC = SortDirection(enums_pb2.SORT_DIRECTION_DESC, protocol_token('SortDirection', enums_pb2.SORT_DIRECTION_DESC))


class GroupSortBy(ProtocolEnumValue):
    NAME: ClassVar[Self]
    VALUE: ClassVar[Self]
    CUSTOM: ClassVar[Self]


GroupSortBy.NAME = GroupSortBy(enums_pb2.GROUP_SORT_BY_NAME, protocol_token('GroupSortBy', enums_pb2.GROUP_SORT_BY_NAME))
GroupSortBy.VALUE = GroupSortBy(enums_pb2.GROUP_SORT_BY_VALUE, protocol_token('GroupSortBy', enums_pb2.GROUP_SORT_BY_VALUE))
GroupSortBy.CUSTOM = GroupSortBy(enums_pb2.GROUP_SORT_BY_CUSTOM, protocol_token('GroupSortBy', enums_pb2.GROUP_SORT_BY_CUSTOM))


class SortBy(ProtocolEnumValue):
    X: ClassVar[Self]
    Y: ClassVar[Self]
    CUSTOM: ClassVar[Self]


SortBy.X = SortBy(enums_pb2.SORT_BY_X, protocol_token('SortBy', enums_pb2.SORT_BY_X))
SortBy.Y = SortBy(enums_pb2.SORT_BY_Y, protocol_token('SortBy', enums_pb2.SORT_BY_Y))
SortBy.CUSTOM = SortBy(enums_pb2.SORT_BY_CUSTOM, protocol_token('SortBy', enums_pb2.SORT_BY_CUSTOM))


class StackMode(ProtocolEnumValue):
    GROUPED: ClassVar[Self]
    STACKED: ClassVar[Self]
    STACKED_100: ClassVar[Self]


StackMode.GROUPED = StackMode(enums_pb2.STACK_MODE_GROUPED, protocol_token('StackMode', enums_pb2.STACK_MODE_GROUPED))
StackMode.STACKED = StackMode(enums_pb2.STACK_MODE_STACKED, protocol_token('StackMode', enums_pb2.STACK_MODE_STACKED))
StackMode.STACKED_100 = StackMode(enums_pb2.STACK_MODE_STACKED_100, protocol_token('StackMode', enums_pb2.STACK_MODE_STACKED_100))


class DateBucket(ProtocolEnumValue):
    EXACT: ClassVar[Self]
    YEAR: ClassVar[Self]
    QUARTER: ClassVar[Self]
    MONTH: ClassVar[Self]
    WEEK: ClassVar[Self]
    DAY: ClassVar[Self]
    HOUR: ClassVar[Self]


DateBucket.EXACT = DateBucket(enums_pb2.DATE_BUCKET_EXACT, protocol_token('DateBucket', enums_pb2.DATE_BUCKET_EXACT))
DateBucket.YEAR = DateBucket(enums_pb2.DATE_BUCKET_YEAR, protocol_token('DateBucket', enums_pb2.DATE_BUCKET_YEAR))
DateBucket.QUARTER = DateBucket(enums_pb2.DATE_BUCKET_QUARTER, protocol_token('DateBucket', enums_pb2.DATE_BUCKET_QUARTER))
DateBucket.MONTH = DateBucket(enums_pb2.DATE_BUCKET_MONTH, protocol_token('DateBucket', enums_pb2.DATE_BUCKET_MONTH))
DateBucket.WEEK = DateBucket(enums_pb2.DATE_BUCKET_WEEK, protocol_token('DateBucket', enums_pb2.DATE_BUCKET_WEEK))
DateBucket.DAY = DateBucket(enums_pb2.DATE_BUCKET_DAY, protocol_token('DateBucket', enums_pb2.DATE_BUCKET_DAY))
DateBucket.HOUR = DateBucket(enums_pb2.DATE_BUCKET_HOUR, protocol_token('DateBucket', enums_pb2.DATE_BUCKET_HOUR))


class DateOrdinal(ProtocolEnumValue):
    DAY_OF_WEEK: ClassVar[Self]
    MONTH_OF_YEAR: ClassVar[Self]
    QUARTER_OF_YEAR: ClassVar[Self]


DateOrdinal.DAY_OF_WEEK = DateOrdinal(enums_pb2.DATE_ORDINAL_DAY_OF_WEEK, protocol_token('DateOrdinal', enums_pb2.DATE_ORDINAL_DAY_OF_WEEK))
DateOrdinal.MONTH_OF_YEAR = DateOrdinal(enums_pb2.DATE_ORDINAL_MONTH_OF_YEAR, protocol_token('DateOrdinal', enums_pb2.DATE_ORDINAL_MONTH_OF_YEAR))
DateOrdinal.QUARTER_OF_YEAR = DateOrdinal(enums_pb2.DATE_ORDINAL_QUARTER_OF_YEAR, protocol_token('DateOrdinal', enums_pb2.DATE_ORDINAL_QUARTER_OF_YEAR))


class AxisScale(ProtocolEnumValue):
    LINEAR: ClassVar[Self]
    LOG: ClassVar[Self]


AxisScale.LINEAR = AxisScale(enums_pb2.AXIS_SCALE_LINEAR, protocol_token('AxisScale', enums_pb2.AXIS_SCALE_LINEAR))
AxisScale.LOG = AxisScale(enums_pb2.AXIS_SCALE_LOG, protocol_token('AxisScale', enums_pb2.AXIS_SCALE_LOG))


class DisplayUnits(ProtocolEnumValue):
    NONE: ClassVar[Self]
    THOUSANDS: ClassVar[Self]
    MILLIONS: ClassVar[Self]
    BILLIONS: ClassVar[Self]
    PERCENT: ClassVar[Self]


DisplayUnits.NONE = DisplayUnits(enums_pb2.DISPLAY_UNITS_NONE, protocol_token('DisplayUnits', enums_pb2.DISPLAY_UNITS_NONE))
DisplayUnits.THOUSANDS = DisplayUnits(enums_pb2.DISPLAY_UNITS_THOUSANDS, protocol_token('DisplayUnits', enums_pb2.DISPLAY_UNITS_THOUSANDS))
DisplayUnits.MILLIONS = DisplayUnits(enums_pb2.DISPLAY_UNITS_MILLIONS, protocol_token('DisplayUnits', enums_pb2.DISPLAY_UNITS_MILLIONS))
DisplayUnits.BILLIONS = DisplayUnits(enums_pb2.DISPLAY_UNITS_BILLIONS, protocol_token('DisplayUnits', enums_pb2.DISPLAY_UNITS_BILLIONS))
DisplayUnits.PERCENT = DisplayUnits(enums_pb2.DISPLAY_UNITS_PERCENT, protocol_token('DisplayUnits', enums_pb2.DISPLAY_UNITS_PERCENT))


class LegendPosition(ProtocolEnumValue):
    TOP: ClassVar[Self]
    BOTTOM: ClassVar[Self]
    LEFT: ClassVar[Self]
    RIGHT: ClassVar[Self]
    NONE: ClassVar[Self]


LegendPosition.TOP = LegendPosition(enums_pb2.LEGEND_POSITION_TOP, protocol_token('LegendPosition', enums_pb2.LEGEND_POSITION_TOP))
LegendPosition.BOTTOM = LegendPosition(enums_pb2.LEGEND_POSITION_BOTTOM, protocol_token('LegendPosition', enums_pb2.LEGEND_POSITION_BOTTOM))
LegendPosition.LEFT = LegendPosition(enums_pb2.LEGEND_POSITION_LEFT, protocol_token('LegendPosition', enums_pb2.LEGEND_POSITION_LEFT))
LegendPosition.RIGHT = LegendPosition(enums_pb2.LEGEND_POSITION_RIGHT, protocol_token('LegendPosition', enums_pb2.LEGEND_POSITION_RIGHT))
LegendPosition.NONE = LegendPosition(enums_pb2.LEGEND_POSITION_NONE, protocol_token('LegendPosition', enums_pb2.LEGEND_POSITION_NONE))


class ChartHeight(ProtocolEnumValue):
    SMALL: ClassVar[Self]
    MEDIUM: ClassVar[Self]
    LARGE: ClassVar[Self]
    XLARGE: ClassVar[Self]


ChartHeight.SMALL = ChartHeight(enums_pb2.CHART_HEIGHT_SMALL, protocol_token('ChartHeight', enums_pb2.CHART_HEIGHT_SMALL))
ChartHeight.MEDIUM = ChartHeight(enums_pb2.CHART_HEIGHT_MEDIUM, protocol_token('ChartHeight', enums_pb2.CHART_HEIGHT_MEDIUM))
ChartHeight.LARGE = ChartHeight(enums_pb2.CHART_HEIGHT_LARGE, protocol_token('ChartHeight', enums_pb2.CHART_HEIGHT_LARGE))
ChartHeight.XLARGE = ChartHeight(enums_pb2.CHART_HEIGHT_XLARGE, protocol_token('ChartHeight', enums_pb2.CHART_HEIGHT_XLARGE))


class ChartWidth(ProtocolEnumValue):
    NORMAL: ClassVar[Self]
    WIDE: ClassVar[Self]
    FULL: ClassVar[Self]


ChartWidth.NORMAL = ChartWidth(enums_pb2.CHART_WIDTH_NORMAL, protocol_token('ChartWidth', enums_pb2.CHART_WIDTH_NORMAL))
ChartWidth.WIDE = ChartWidth(enums_pb2.CHART_WIDTH_WIDE, protocol_token('ChartWidth', enums_pb2.CHART_WIDTH_WIDE))
ChartWidth.FULL = ChartWidth(enums_pb2.CHART_WIDTH_FULL, protocol_token('ChartWidth', enums_pb2.CHART_WIDTH_FULL))


class RecipientSource(ProtocolEnumValue):
    MANUAL: ClassVar[Self]
    COLUMN: ClassVar[Self]


RecipientSource.MANUAL = RecipientSource(enums_pb2.RECIPIENT_SOURCE_MANUAL, protocol_token('RecipientSource', enums_pb2.RECIPIENT_SOURCE_MANUAL))
RecipientSource.COLUMN = RecipientSource(enums_pb2.RECIPIENT_SOURCE_COLUMN, protocol_token('RecipientSource', enums_pb2.RECIPIENT_SOURCE_COLUMN))


class DeduplicateKeep(ProtocolEnumValue):
    FIRST: ClassVar[Self]
    LAST: ClassVar[Self]
    ANY: ClassVar[Self]
    NONE: ClassVar[Self]

    @property
    def polars_keep(self) -> Literal['first', 'last', 'any', 'none']:
        return cast(Literal['first', 'last', 'any', 'none'], self.value)


DeduplicateKeep.FIRST = DeduplicateKeep(enums_pb2.DEDUPLICATE_KEEP_FIRST, protocol_token('DeduplicateKeep', enums_pb2.DEDUPLICATE_KEEP_FIRST))
DeduplicateKeep.LAST = DeduplicateKeep(enums_pb2.DEDUPLICATE_KEEP_LAST, protocol_token('DeduplicateKeep', enums_pb2.DEDUPLICATE_KEEP_LAST))
DeduplicateKeep.ANY = DeduplicateKeep(enums_pb2.DEDUPLICATE_KEEP_ANY, protocol_token('DeduplicateKeep', enums_pb2.DEDUPLICATE_KEEP_ANY))
DeduplicateKeep.NONE = DeduplicateKeep(enums_pb2.DEDUPLICATE_KEEP_NONE, protocol_token('DeduplicateKeep', enums_pb2.DEDUPLICATE_KEEP_NONE))


class PivotAggregateFunction(ProtocolEnumValue):
    FIRST: ClassVar[Self]
    LAST: ClassVar[Self]
    SUM: ClassVar[Self]
    MEAN: ClassVar[Self]
    MEDIAN: ClassVar[Self]
    MIN: ClassVar[Self]
    MAX: ClassVar[Self]
    COUNT: ClassVar[Self]

    @property
    def polars_aggregate_function(self) -> Literal['first', 'last', 'sum', 'mean', 'median', 'min', 'max', 'len']:
        if self == PivotAggregateFunction.COUNT:
            return 'len'
        return cast(Literal['first', 'last', 'sum', 'mean', 'median', 'min', 'max'], self.value)


PivotAggregateFunction.FIRST = PivotAggregateFunction(
    enums_pb2.PIVOT_AGGREGATE_FUNCTION_FIRST, protocol_token('PivotAggregateFunction', enums_pb2.PIVOT_AGGREGATE_FUNCTION_FIRST)
)
PivotAggregateFunction.LAST = PivotAggregateFunction(
    enums_pb2.PIVOT_AGGREGATE_FUNCTION_LAST, protocol_token('PivotAggregateFunction', enums_pb2.PIVOT_AGGREGATE_FUNCTION_LAST)
)
PivotAggregateFunction.SUM = PivotAggregateFunction(
    enums_pb2.PIVOT_AGGREGATE_FUNCTION_SUM, protocol_token('PivotAggregateFunction', enums_pb2.PIVOT_AGGREGATE_FUNCTION_SUM)
)
PivotAggregateFunction.MEAN = PivotAggregateFunction(
    enums_pb2.PIVOT_AGGREGATE_FUNCTION_MEAN, protocol_token('PivotAggregateFunction', enums_pb2.PIVOT_AGGREGATE_FUNCTION_MEAN)
)
PivotAggregateFunction.MEDIAN = PivotAggregateFunction(
    enums_pb2.PIVOT_AGGREGATE_FUNCTION_MEDIAN, protocol_token('PivotAggregateFunction', enums_pb2.PIVOT_AGGREGATE_FUNCTION_MEDIAN)
)
PivotAggregateFunction.MIN = PivotAggregateFunction(
    enums_pb2.PIVOT_AGGREGATE_FUNCTION_MIN, protocol_token('PivotAggregateFunction', enums_pb2.PIVOT_AGGREGATE_FUNCTION_MIN)
)
PivotAggregateFunction.MAX = PivotAggregateFunction(
    enums_pb2.PIVOT_AGGREGATE_FUNCTION_MAX, protocol_token('PivotAggregateFunction', enums_pb2.PIVOT_AGGREGATE_FUNCTION_MAX)
)
PivotAggregateFunction.COUNT = PivotAggregateFunction(
    enums_pb2.PIVOT_AGGREGATE_FUNCTION_COUNT, protocol_token('PivotAggregateFunction', enums_pb2.PIVOT_AGGREGATE_FUNCTION_COUNT)
)


class FillNullStrategy(ProtocolEnumValue):
    FORWARD: ClassVar[Self]
    BACKWARD: ClassVar[Self]
    MEAN: ClassVar[Self]
    MEDIAN: ClassVar[Self]
    ZERO: ClassVar[Self]
    LITERAL: ClassVar[Self]
    DROP_ROWS: ClassVar[Self]

    @property
    def uses_literal_value(self) -> bool:
        return self == FillNullStrategy.LITERAL

    @property
    def drops_rows(self) -> bool:
        return self == FillNullStrategy.DROP_ROWS


FillNullStrategy.FORWARD = FillNullStrategy(enums_pb2.FILL_NULL_STRATEGY_FORWARD, protocol_token('FillNullStrategy', enums_pb2.FILL_NULL_STRATEGY_FORWARD))
FillNullStrategy.BACKWARD = FillNullStrategy(enums_pb2.FILL_NULL_STRATEGY_BACKWARD, protocol_token('FillNullStrategy', enums_pb2.FILL_NULL_STRATEGY_BACKWARD))
FillNullStrategy.MEAN = FillNullStrategy(enums_pb2.FILL_NULL_STRATEGY_MEAN, protocol_token('FillNullStrategy', enums_pb2.FILL_NULL_STRATEGY_MEAN))
FillNullStrategy.MEDIAN = FillNullStrategy(enums_pb2.FILL_NULL_STRATEGY_MEDIAN, protocol_token('FillNullStrategy', enums_pb2.FILL_NULL_STRATEGY_MEDIAN))
FillNullStrategy.ZERO = FillNullStrategy(enums_pb2.FILL_NULL_STRATEGY_ZERO, protocol_token('FillNullStrategy', enums_pb2.FILL_NULL_STRATEGY_ZERO))
FillNullStrategy.LITERAL = FillNullStrategy(enums_pb2.FILL_NULL_STRATEGY_LITERAL, protocol_token('FillNullStrategy', enums_pb2.FILL_NULL_STRATEGY_LITERAL))
FillNullStrategy.DROP_ROWS = FillNullStrategy(
    enums_pb2.FILL_NULL_STRATEGY_DROP_ROWS, protocol_token('FillNullStrategy', enums_pb2.FILL_NULL_STRATEGY_DROP_ROWS)
)
