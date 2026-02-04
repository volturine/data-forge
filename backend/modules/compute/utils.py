import time

import polars as pl

from core.config import settings
from core.exceptions import EngineTimeoutError, StepNotFoundError


def find_step_index(pipeline_steps: list[dict], target_step_id: str) -> int:
    for idx, step in enumerate(pipeline_steps):
        if step.get('id') == target_step_id:
            return idx
    raise StepNotFoundError(target_step_id)


def await_engine_result(engine, timeout: int) -> dict:
    start_time = time.time()
    while True:
        if time.time() - start_time > timeout:
            raise EngineTimeoutError(f'Operation timed out after {timeout} seconds', timeout)

        result_data = engine.get_result(timeout=0.1)
        if result_data:
            return result_data

        time.sleep(0.1)


def build_datasource_config(datasource) -> dict:
    return {
        'source_type': datasource.source_type,
        **datasource.config,
    }


def normalize_timezones(lf: pl.LazyFrame, schema: pl.Schema | None = None) -> pl.LazyFrame:
    if not settings.normalize_tz:
        return lf

    schema = schema or lf.collect_schema()
    exprs: list[pl.Expr] = []

    for name, dtype in schema.items():
        if not isinstance(dtype, pl.Datetime):
            continue
        tz = dtype.time_zone
        if tz is None:
            exprs.append(pl.col(name).dt.replace_time_zone(settings.timezone).alias(name))
            continue
        exprs.append(pl.col(name).dt.convert_time_zone(settings.timezone).alias(name))

    if not exprs:
        return lf
    return lf.with_columns(exprs)
