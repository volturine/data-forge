from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import polars as pl
from contracts.compute.base import OperationHandler, OperationParams
from contracts.step_config_enums import FilterLogic, FilterOperator, FilterValueType
from core.config import settings
from pydantic import BaseModel, ConfigDict, Field, model_validator

from operations.validation import validate_regex_pattern

FilterExpr = Callable[[pl.Expr, Any], pl.Expr]
ColumnFilterExpr = Callable[[pl.Expr, pl.Expr], pl.Expr]


@dataclass(frozen=True, slots=True)
class FilterOperatorDefinition:
    operator: FilterOperator
    expression: FilterExpr
    column_expression: ColumnFilterExpr | None = None

    @classmethod
    def require(cls, operator: FilterOperator | str) -> "FilterOperatorDefinition":
        parsed = FilterOperator.require_supported(operator)
        for definition in FILTER_OPERATOR_DEFINITIONS:
            if definition.operator == parsed:
                return definition
        raise ValueError(FilterOperator.unsupported_message(parsed.value))

    def apply(self, left: pl.Expr, value: Any) -> pl.Expr:
        return self.expression(left, value)

    def apply_value(self, left: pl.Expr, value: Any) -> pl.Expr:
        if (empty_result := self.operator.empty_string_result) is not None and value == "":
            return pl.lit(empty_result)
        if self.operator.requires_regex_validation and isinstance(value, str):
            validate_regex_pattern(value)
        if isinstance(value, list):
            return self.apply_list(left, value)
        return self.apply(left, value)

    def apply_list(self, left: pl.Expr, values: list[Any]) -> pl.Expr:
        if not values:
            return pl.lit(self.operator.empty_list_result)
        if self.operator.is_membership:
            return self.apply(left, values)
        expressions = [self.apply(left, item) for item in values]
        combiner = pl.all_horizontal if self.operator.folds_list_with_all else pl.any_horizontal
        return combiner(expressions)

    def apply_column(self, left: pl.Expr, right: pl.Expr) -> pl.Expr:
        if self.column_expression is None:
            raise ValueError(f"Operator {self.operator.value} not supported for column comparison")
        return self.column_expression(left, right)


FILTER_OPERATOR_DEFINITIONS: tuple[FilterOperatorDefinition, ...] = (
    FilterOperatorDefinition(FilterOperator.EQUAL, lambda left, right: left == right, lambda left, right: left == right),
    FilterOperatorDefinition(FilterOperator.DOUBLE_EQUAL, lambda left, right: left == right, lambda left, right: left == right),
    FilterOperatorDefinition(FilterOperator.NOT_EQUAL, lambda left, right: left != right, lambda left, right: left != right),
    FilterOperatorDefinition(FilterOperator.GREATER_THAN, lambda left, right: left > right, lambda left, right: left > right),
    FilterOperatorDefinition(FilterOperator.LESS_THAN, lambda left, right: left < right, lambda left, right: left < right),
    FilterOperatorDefinition(FilterOperator.GREATER_EQUAL, lambda left, right: left >= right, lambda left, right: left >= right),
    FilterOperatorDefinition(FilterOperator.LESS_EQUAL, lambda left, right: left <= right, lambda left, right: left <= right),
    FilterOperatorDefinition(FilterOperator.CONTAINS, lambda left, value: left.str.contains(value, literal=True)),
    FilterOperatorDefinition(FilterOperator.NOT_CONTAINS, lambda left, value: ~left.str.contains(value, literal=True)),
    FilterOperatorDefinition(FilterOperator.STARTS_WITH, lambda left, value: left.str.starts_with(value)),
    FilterOperatorDefinition(FilterOperator.ENDS_WITH, lambda left, value: left.str.ends_with(value)),
    FilterOperatorDefinition(FilterOperator.REGEX, lambda left, value: left.str.contains(value, literal=False)),
    FilterOperatorDefinition(FilterOperator.IS_NULL, lambda left, _: left.is_null()),
    FilterOperatorDefinition(FilterOperator.IS_NOT_NULL, lambda left, _: left.is_not_null()),
    FilterOperatorDefinition(FilterOperator.IN, lambda left, value: left.is_in(value)),
    FilterOperatorDefinition(FilterOperator.NOT_IN, lambda left, value: ~left.is_in(value)),
)


class FilterCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str
    operator: FilterOperator = FilterOperator.DOUBLE_EQUAL
    value: Any | list[Any] | None = None
    value_type: FilterValueType = FilterValueType.STRING
    compare_column: str | None = None

    @staticmethod
    def normalize_text(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        return value.strip()

    @classmethod
    def normalize_many(cls, conditions: list[Any] | None) -> list[Any]:
        if not conditions:
            return []

        normalized: list[Any] = []
        for condition in conditions:
            if not isinstance(condition, dict):
                normalized.append(condition)
                continue

            column = cls.normalize_text(condition.get("column"))
            if not column:
                continue

            operator = FilterOperator.require_supported(condition.get("operator") or FilterOperator.EQUAL.value)
            value_type = FilterValueType.require(condition.get("value_type", FilterValueType.STRING.value))
            item: dict[str, Any] = {
                "column": column,
                "operator": operator.value,
                "value": condition.get("value"),
                "value_type": value_type.value,
            }

            if operator.is_null_check:
                normalized.append(item)
                continue

            compare_column = cls.normalize_text(condition.get("compare_column"))
            if value_type == FilterValueType.COLUMN and not compare_column:
                continue
            if compare_column:
                item["compare_column"] = compare_column

            normalized.append(item)

        return normalized

    @property
    def uses_column_value(self) -> bool:
        return self.value_type == FilterValueType.COLUMN

    @model_validator(mode="after")
    def validate_condition(self) -> "FilterCondition":
        if self.operator.is_null_check:
            return self
        if self.uses_column_value and not self.compare_column:
            raise ValueError("compare_column required when value_type is column")
        if not self.uses_column_value and self.value is None:
            raise ValueError("value required for non-column comparisons")
        return self

    def expression(self, schema: pl.Schema) -> pl.Expr:
        definition = FilterOperatorDefinition.require(self.operator)
        left = self.left_expression(schema)

        if self.operator.is_null_check:
            return definition.apply(left, None)

        if self.uses_column_value:
            return definition.apply_column(left, self.right_column_expression(schema))

        coerced = self.coerced_value(schema)
        return definition.apply_value(left, coerced)

    def left_expression(self, schema: pl.Schema) -> pl.Expr:
        expr = pl.col(self.column)
        if dtype := schema.get(self.column):
            return self.normalize_datetime_column(expr, dtype)
        return expr

    def right_column_expression(self, schema: pl.Schema) -> pl.Expr:
        if not self.compare_column:
            raise ValueError("compare_column required when value_type is column")
        expr = pl.col(self.compare_column)
        if self.compare_column in schema:
            return self.normalize_datetime_column(expr, schema[self.compare_column])
        return expr

    def coerced_value(self, schema: pl.Schema) -> Any:
        value_type = FilterValueType.DATE if self.compares_date_only_datetime(schema) else self.value_type
        return value_type.coerce(self.value, normalize_tz=settings.normalize_tz, timezone=settings.timezone)

    def compares_date_only_datetime(self, schema: pl.Schema) -> bool:
        return self.value_type == FilterValueType.DATETIME and isinstance(schema.get(self.column), pl.Datetime) and self.is_date_only_value()

    def is_date_only_value(self) -> bool:
        return isinstance(self.value, str) and len(self.value) == 10 and "-" in self.value and "T" not in self.value

    @staticmethod
    def normalize_datetime_column(expr: pl.Expr, dtype: pl.DataType) -> pl.Expr:
        if not isinstance(dtype, pl.Datetime):
            return expr
        tz = dtype.time_zone
        if settings.normalize_tz:
            if tz is None:
                return expr.dt.replace_time_zone(settings.timezone)
            return expr.dt.convert_time_zone(settings.timezone)
        if tz is None:
            return expr
        return expr.dt.replace_time_zone(None)


class FilterParams(OperationParams):
    conditions: list[FilterCondition] = Field(default_factory=list)
    logic: FilterLogic = FilterLogic.AND

    @model_validator(mode="before")
    @classmethod
    def normalize_conditions(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        return {
            **data,
            "conditions": FilterCondition.normalize_many(data.get("conditions")),
        }


class FilterHandler(OperationHandler):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        **_,
    ) -> pl.LazyFrame:
        validated = FilterParams.model_validate(params)
        if not validated.conditions:
            return lf

        schema = lf.collect_schema()

        exprs = [condition.expression(schema) for condition in validated.conditions]

        combiners: dict[str, Callable[[list[pl.Expr]], pl.Expr]] = {
            "all": pl.all_horizontal,
            "any": pl.any_horizontal,
        }
        return lf.filter(combiners[validated.logic.expression_combiner](exprs))
