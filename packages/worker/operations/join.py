import polars as pl
from pydantic import BaseModel, ConfigDict

from operations.enums import JoinHow
from runtime.domain.compute.base import OperationParams


class JoinColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    left_column: str
    right_column: str


class JoinParams(OperationParams):
    right_source: str | None = None
    join_columns: list[JoinColumn] | None = None
    right_columns: list[str] | None = None
    how: JoinHow = JoinHow.INNER
    suffix: str = "_right"


def join(
    lf: pl.LazyFrame,
    params: JoinParams,
    *,
    right_lf: pl.LazyFrame | None = None,
    **_,
) -> pl.LazyFrame:
    right_columns = params.right_columns or []
    left_columns = lf.collect_schema().names()

    if right_lf is None:
        raise ValueError("Join requires a right datasource")
    right_schema_columns = right_lf.collect_schema().names()

    if not params.how.requires_join_keys:
        return lf.join(right_lf, how=params.how.polars_how)

    join_columns = params.join_columns or []
    left_on = [col.left_column for col in join_columns if col.left_column]
    right_on = [col.right_column for col in join_columns if col.right_column]

    if not left_on or not right_on:
        raise ValueError("Join requires at least one join column pair")

    joined = lf.join(
        right_lf,
        left_on=left_on,
        right_on=right_on,
        how=params.how.polars_how,
        suffix=params.suffix,
    )

    if right_columns:
        missing = [column for column in right_columns if column not in right_schema_columns]
        if missing:
            cols = ", ".join(missing)
            raise ValueError(f"Join right_columns reference unknown column(s): {cols}")

        all_columns = joined.collect_schema().names()
        left_column_set = set(left_columns)
        selected_columns = left_column_set | {f"{column}{params.suffix}" if column in left_column_set else column for column in right_columns}
        final_columns = [column for column in all_columns if column in selected_columns]
        return joined.select(final_columns)

    return joined
