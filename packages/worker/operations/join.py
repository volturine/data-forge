import polars as pl
from pydantic import BaseModel, ConfigDict

from worker_contracts.compute.base import OperationHandler, OperationParams
from worker_contracts.step_config_enums import JoinHow


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
    left_on: list[str] | None = None
    right_on: list[str] | None = None


class JoinHandler(OperationHandler):
    def __call__(
        self,
        lf: pl.LazyFrame,
        params: dict,
        *,
        right_lf: pl.LazyFrame | None = None,
        **_,
    ) -> pl.LazyFrame:
        validated = JoinParams.model_validate(params)
        right_columns = validated.right_columns or []
        left_columns = lf.collect_schema().names()

        if right_lf is None:
            raise ValueError("Join requires a right datasource")
        right_schema_columns = right_lf.collect_schema().names()

        if not validated.how.requires_join_keys:
            return lf.join(right_lf, how=validated.how.polars_how)

        join_columns = validated.join_columns or []
        left_on = validated.left_on or []
        right_on = validated.right_on or []
        if join_columns:
            left_on = [col.left_column for col in join_columns if col.left_column]
            right_on = [col.right_column for col in join_columns if col.right_column]

        if not left_on or not right_on:
            raise ValueError("Join requires at least one join column pair")

        joined = lf.join(
            right_lf,
            left_on=left_on,
            right_on=right_on,
            how=validated.how.polars_how,
            suffix=validated.suffix,
        )

        if right_columns:
            missing = [column for column in right_columns if column not in right_schema_columns]
            if missing:
                cols = ", ".join(missing)
                raise ValueError(f"Join right_columns reference unknown column(s): {cols}")

            all_columns = joined.collect_schema().names()
            selected_columns = set(left_columns)
            selected_right_columns = set(right_columns)
            left_column_set = set(left_columns)

            for column in right_columns:
                if column in left_column_set:
                    suffixed = f"{column}{validated.suffix}"
                    if suffixed in all_columns:
                        selected_columns.add(suffixed)
                    elif column in all_columns and column in selected_right_columns:
                        selected_columns.add(column)
                    continue

                if column in all_columns:
                    selected_columns.add(column)

            final_columns = [column for column in all_columns if column in selected_columns]
            return joined.select(final_columns)

        return joined
