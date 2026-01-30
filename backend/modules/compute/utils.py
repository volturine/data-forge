import asyncio
import time

from core.exceptions import EngineTimeoutError, StepNotFoundError


def find_step_index(pipeline_steps: list[dict], target_step_id: str) -> int:
    for idx, step in enumerate(pipeline_steps):
        if step.get('id') == target_step_id:
            return idx
    raise StepNotFoundError(target_step_id)


async def await_engine_result(engine, timeout: int) -> dict:
    start_time = time.time()
    while True:
        if time.time() - start_time > timeout:
            raise EngineTimeoutError(f'Operation timed out after {timeout} seconds', timeout)

        result_data = engine.get_result(timeout=0.1)
        if result_data:
            return result_data

        await asyncio.sleep(0.1)


def build_datasource_config(datasource) -> dict:
    return {
        'source_type': datasource.source_type,
        **datasource.config,
    }
