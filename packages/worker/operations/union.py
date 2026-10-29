import polars as pl
from pydantic import Field

from runtime.domain.compute.base import OperationParams


class UnionParams(OperationParams):
    sources: list[str] = Field(min_length=1)
    allow_missing: bool = True


def union_by_name(
    lf: pl.LazyFrame,
    params: UnionParams,
    *,
    right_sources: dict[str, pl.LazyFrame] | None = None,
    **_,
) -> pl.LazyFrame:
    frames: list[pl.LazyFrame] = [lf]
    sources_map = right_sources or {}
    for source_id in params.sources:
        frame = sources_map.get(source_id)
        if frame is None:
            raise ValueError(f"Union by name requires datasource {source_id}")
        frames.append(frame)

    if not params.allow_missing:
        base_columns = lf.collect_schema().names()
        base_set = set(base_columns)
        aligned = [lf]
        for frame in frames[1:]:
            frame_columns = frame.collect_schema().names()
            if set(frame_columns) != base_set:
                raise ValueError("Union by name requires matching columns when allow_missing is false")
            aligned.append(frame.select(base_columns))
        return pl.concat(aligned, how="vertical")

    return pl.concat(frames, how="diagonal")
