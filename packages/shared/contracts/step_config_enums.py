from contracts.enums import DataForgeStrEnum


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
        if self == DurationUnit.SECONDS:
            return '1s'
        if self == DurationUnit.MINUTES:
            return '1m'
        if self == DurationUnit.HOURS:
            return '1h'
        if self == DurationUnit.DAYS:
            return '1d'
        if self == DurationUnit.WEEKS:
            return '1w'
        return '1mo'


class TimeDirection(DataForgeStrEnum):
    ADD = 'add'
    SUBTRACT = 'subtract'


class WithColumnsExprType(DataForgeStrEnum):
    LITERAL = 'literal'
    COLUMN = 'column'
    UDF = 'udf'


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
