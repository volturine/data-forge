from datetime import datetime
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

from contracts.enums import DataForgeStrEnum


class FilterValueType(DataForgeStrEnum):
    STRING = 'string'
    NUMBER = 'number'
    DATE = 'date'
    DATETIME = 'datetime'
    COLUMN = 'column'
    BOOLEAN = 'boolean'

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


class FilterLogic(DataForgeStrEnum):
    AND = 'AND'
    OR = 'OR'

    @property
    def expression_combiner(self) -> str:
        return 'all' if self == FilterLogic.AND else 'any'


class FilterOperator(DataForgeStrEnum):
    EQUAL = '='
    DOUBLE_EQUAL = '=='
    NOT_EQUAL = '!='
    GREATER_THAN = '>'
    LESS_THAN = '<'
    GREATER_EQUAL = '>='
    LESS_EQUAL = '<='
    CONTAINS = 'contains'
    NOT_CONTAINS = 'not_contains'
    STARTS_WITH = 'starts_with'
    ENDS_WITH = 'ends_with'
    REGEX = 'regex'
    IS_NULL = 'is_null'
    IS_NOT_NULL = 'is_not_null'
    IN = 'in'
    NOT_IN = 'not_in'

    @classmethod
    def unsupported_message(cls, value: object) -> str:
        return f'Unsupported filter operator: {value}'

    @classmethod
    def require_supported(cls, value: object) -> 'FilterOperator':
        try:
            return cls.require(value)  # type: ignore[arg-type]
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


class StringTransformMethod(DataForgeStrEnum):
    UPPERCASE = 'uppercase'
    LOWERCASE = 'lowercase'
    TITLE = 'title'
    STRIP = 'strip'
    LSTRIP = 'lstrip'
    RSTRIP = 'rstrip'
    LENGTH = 'length'
    SLICE = 'slice'
    REPLACE = 'replace'
    EXTRACT = 'extract'
    SPLIT = 'split'
    SPLIT_TAKE = 'split_take'


class TimeseriesOperationType(DataForgeStrEnum):
    EXTRACT = 'extract'
    TIMESTAMP = 'timestamp'
    ADD = 'add'
    SUBTRACT = 'subtract'
    OFFSET = 'offset'
    DIFF = 'diff'
    TRUNCATE = 'truncate'
    ROUND = 'round'


class TimeComponent(DataForgeStrEnum):
    YEAR = 'year'
    MONTH = 'month'
    DAY = 'day'
    HOUR = 'hour'
    MINUTE = 'minute'
    SECOND = 'second'
    QUARTER = 'quarter'
    WEEK = 'week'
    DAYOFWEEK = 'dayofweek'

    @property
    def extractor_name(self) -> str:
        if self == TimeComponent.DAYOFWEEK:
            return 'weekday'
        return self.value


class DurationUnit(DataForgeStrEnum):
    SECONDS = 'seconds'
    MINUTES = 'minutes'
    HOURS = 'hours'
    DAYS = 'days'
    WEEKS = 'weeks'
    MONTHS = 'months'

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


class TimeDirection(DataForgeStrEnum):
    ADD = 'add'
    SUBTRACT = 'subtract'


class WithColumnsExprType(DataForgeStrEnum):
    LITERAL = 'literal'
    COLUMN = 'column'
    UDF = 'udf'


class NotificationMethod(DataForgeStrEnum):
    EMAIL = 'email'
    TELEGRAM = 'telegram'


class JoinHow(DataForgeStrEnum):
    INNER = 'inner'
    LEFT = 'left'
    RIGHT = 'right'
    OUTER = 'outer'
    CROSS = 'cross'

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


class GroupByAggregationFunction(DataForgeStrEnum):
    SUM = 'sum'
    MEAN = 'mean'
    COUNT = 'count'
    MIN = 'min'
    MAX = 'max'
    FIRST = 'first'
    LAST = 'last'
    MEDIAN = 'median'
    STD = 'std'
    N_UNIQUE = 'n_unique'
    COLLECT_LIST = 'collect_list'
    COLLECT_SET = 'collect_set'

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


class ChartAggregation(DataForgeStrEnum):
    SUM = 'sum'
    MEAN = 'mean'
    COUNT = 'count'
    MIN = 'min'
    MAX = 'max'
    MEDIAN = 'median'
    STD = 'std'
    VARIANCE = 'variance'
    UNIQUE_COUNT = 'unique_count'


class OverlayChartType(DataForgeStrEnum):
    LINE = 'line'
    AREA = 'area'
    BAR = 'bar'
    SCATTER = 'scatter'


class YAxisPosition(DataForgeStrEnum):
    LEFT = 'left'
    RIGHT = 'right'


class ReferenceAxis(DataForgeStrEnum):
    X = 'x'
    Y = 'y'


class SortDirection(DataForgeStrEnum):
    ASC = 'asc'
    DESC = 'desc'


class GroupSortBy(DataForgeStrEnum):
    NAME = 'name'
    VALUE = 'value'
    CUSTOM = 'custom'


class SortBy(DataForgeStrEnum):
    X = 'x'
    Y = 'y'
    CUSTOM = 'custom'


class StackMode(DataForgeStrEnum):
    GROUPED = 'grouped'
    STACKED = 'stacked'
    STACKED_100 = '100%'


class DateBucket(DataForgeStrEnum):
    EXACT = 'exact'
    YEAR = 'year'
    QUARTER = 'quarter'
    MONTH = 'month'
    WEEK = 'week'
    DAY = 'day'
    HOUR = 'hour'


class DateOrdinal(DataForgeStrEnum):
    DAY_OF_WEEK = 'day_of_week'
    MONTH_OF_YEAR = 'month_of_year'
    QUARTER_OF_YEAR = 'quarter_of_year'


class AxisScale(DataForgeStrEnum):
    LINEAR = 'linear'
    LOG = 'log'


class DisplayUnits(DataForgeStrEnum):
    NONE = ''
    THOUSANDS = 'K'
    MILLIONS = 'M'
    BILLIONS = 'B'
    PERCENT = '%'


class LegendPosition(DataForgeStrEnum):
    TOP = 'top'
    BOTTOM = 'bottom'
    LEFT = 'left'
    RIGHT = 'right'
    NONE = 'none'


class ChartHeight(DataForgeStrEnum):
    SMALL = 'small'
    MEDIUM = 'medium'
    LARGE = 'large'
    XLARGE = 'xlarge'


class ChartWidth(DataForgeStrEnum):
    NORMAL = 'normal'
    WIDE = 'wide'
    FULL = 'full'


class RecipientSource(DataForgeStrEnum):
    MANUAL = 'manual'
    COLUMN = 'column'


class AIProvider(DataForgeStrEnum):
    OLLAMA = 'ollama'
    OPENAI = 'openai'
    OPENROUTER = 'openrouter'
    HUGGINGFACE = 'huggingface'


class DeduplicateKeep(DataForgeStrEnum):
    FIRST = 'first'
    LAST = 'last'
    ANY = 'any'
    NONE = 'none'

    @property
    def polars_keep(self) -> Literal['first', 'last', 'any', 'none']:
        return self.value


class PivotAggregateFunction(DataForgeStrEnum):
    FIRST = 'first'
    LAST = 'last'
    SUM = 'sum'
    MEAN = 'mean'
    MEDIAN = 'median'
    MIN = 'min'
    MAX = 'max'
    COUNT = 'count'

    @property
    def polars_aggregate_function(self) -> Literal['first', 'last', 'sum', 'mean', 'median', 'min', 'max', 'len']:
        if self == PivotAggregateFunction.COUNT:
            return 'len'
        return cast(Literal['first', 'last', 'sum', 'mean', 'median', 'min', 'max'], self.value)


class FillNullStrategy(DataForgeStrEnum):
    FORWARD = 'forward'
    BACKWARD = 'backward'
    MEAN = 'mean'
    MEDIAN = 'median'
    ZERO = 'zero'
    LITERAL = 'literal'
    DROP_ROWS = 'drop_rows'

    @property
    def uses_literal_value(self) -> bool:
        return self == FillNullStrategy.LITERAL

    @property
    def drops_rows(self) -> bool:
        return self == FillNullStrategy.DROP_ROWS
