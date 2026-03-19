from typing import Literal

import polars as pl
from pydantic import BaseModel, ConfigDict

from modules.compute.core.base import OperationHandler, OperationParams


class JoinColumn(BaseModel):
    model_config = ConfigDict(extra='forbid')

    id: str | None = None
    left_column: str
    right_column: str


class JoinParams(OperationParams):
    right_source: str | None = None
    join_columns: list[JoinColumn] | None = None
    right_columns: list[str] | None = None
    how: Literal['inner', 'left', 'right', 'full', 'semi', 'anti', 'cross'] = 'inner'
    suffix: str = '_right'
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
        join_columns = validated.join_columns or []
        right_columns = validated.right_columns or []

        left_on = validated.left_on or []
        right_on = validated.right_on or []
        if join_columns:
            left_on = [col.left_column for col in join_columns if col.left_column]
            right_on = [col.right_column for col in join_columns if col.right_column]

        if not left_on or not right_on:
            raise ValueError('Join requires at least one join column pair')

        if validated.how == 'cross':
            if right_lf is not None:
                return lf.join(right_lf, how='cross')
            return lf.join(lf, how='cross')

        joined = lf.join(
            lf,
            left_on=left_on,
            right_on=right_on,
            how=validated.how,
            suffix=validated.suffix,
        )
        if right_lf is not None and validated.right_source:
            joined = lf.join(
                right_lf,
                left_on=left_on,
                right_on=right_on,
                how=validated.how,
                suffix=validated.suffix,
            )

        if right_columns and validated.how != 'cross':
            all_columns = joined.collect_schema().names()
            final_columns = [
                col for col in all_columns if not col.endswith(validated.suffix) or col[: -len(validated.suffix)] in right_columns
            ]
            if final_columns != all_columns:
                return joined.select(final_columns)

        return joined
