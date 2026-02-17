import contextlib
import logging
import multiprocessing as mp
import os
import resource
import threading
import time
import uuid
from multiprocessing.process import BaseProcess
from queue import Empty

import polars as pl

from core.exceptions import PipelineValidationError
from modules.compute.core.exports import get_export_format
from modules.compute.operations import get_operation_handlers
from modules.compute.operations.datasource import load_datasource
from modules.compute.operations.plot import compute_chart_data
from modules.compute.step_converter import convert_config_to_params, convert_step_format
from modules.compute.utils import apply_pipeline_steps, normalize_timezones

logger = logging.getLogger(__name__)


class PolarsComputeEngine:
    _ENV_LOCK = threading.Lock()

    def __init__(self, analysis_id: str, resource_config: dict | None = None):
        self.analysis_id = analysis_id
        self.resource_config = resource_config or {}
        self.effective_resources: dict = {}  # Populated when engine starts
        self._mp_context = mp.get_context('spawn')
        self.process: BaseProcess | None = None
        self.command_queue: mp.Queue = self._mp_context.Queue()
        self.result_queue: mp.Queue = self._mp_context.Queue()
        self.is_running = False
        self.current_job_id: str | None = None
        self._pending_results: dict[str, dict] = {}

    def is_process_alive(self) -> bool:
        """Check if the subprocess is still alive."""
        return self.process is not None and self.process.is_alive()

    def check_health(self) -> bool:
        """Check process health and reset state if process died unexpectedly.

        Returns:
            True if process is healthy, False if it was dead and state was reset.
        """
        if not self.is_running:
            return True  # Not started, nothing to check

        if self.is_process_alive():
            return True  # Process is running fine

        # Process died unexpectedly - reset state
        logger.warning(
            f'Compute process for analysis {self.analysis_id} died unexpectedly '
            f'(exit code: {self.process.exitcode if self.process else "unknown"}). '
            f'Resetting engine state.'
        )
        self._reset_state()
        return False

    def _reset_state(self) -> None:
        """Reset engine state after process death."""
        self.is_running = False
        self.current_job_id = None
        self._pending_results = {}
        if self.process:
            # Clean up the dead process
            with contextlib.suppress(Exception):
                self.process.join(timeout=1.0)
            self.process = None
        # Close old queues before creating new ones (old ones may be corrupted)
        if hasattr(self, 'command_queue'):
            with contextlib.suppress(Exception):
                self.command_queue.cancel_join_thread()
                self.command_queue.close()
            with contextlib.suppress(Exception):
                self.command_queue.join_thread()
        if hasattr(self, 'result_queue'):
            with contextlib.suppress(Exception):
                self.result_queue.cancel_join_thread()
                self.result_queue.close()
            with contextlib.suppress(Exception):
                self.result_queue.join_thread()
        self.command_queue = self._mp_context.Queue()
        self.result_queue = self._mp_context.Queue()

    def start(self) -> None:
        """Start the compute subprocess."""
        if self.is_running:
            return

        from core.config import settings

        # Determine effective resource values (override > settings)
        # None in resource_config means use settings default
        max_threads = self.resource_config.get('max_threads')
        if max_threads is None:
            max_threads = settings.polars_max_threads

        max_memory_mb = self.resource_config.get('max_memory_mb')
        if max_memory_mb is None:
            max_memory_mb = settings.polars_max_memory_mb

        streaming_chunk_size = self.resource_config.get('streaming_chunk_size')
        if streaming_chunk_size is None:
            streaming_chunk_size = settings.polars_streaming_chunk_size

        # Store effective resources for status reporting
        self.effective_resources = {
            'max_threads': max_threads,
            'max_memory_mb': max_memory_mb,
            'streaming_chunk_size': streaming_chunk_size,
        }

        env_updates: dict[str, str] = {}
        if max_threads > 0:
            env_updates['POLARS_MAX_THREADS'] = str(max_threads)
        if streaming_chunk_size > 0:
            env_updates['POLARS_STREAMING_CHUNK_SIZE'] = str(streaming_chunk_size)

        with self._ENV_LOCK:
            previous_env: dict[str, str | None] = {key: os.environ.get(key) for key in env_updates}
            for key, value in env_updates.items():
                os.environ[key] = value
                logger.debug(f'Set {key}={value} for subprocess spawn')
            try:
                process = self._mp_context.Process(
                    target=self._run_compute,
                    args=(self.command_queue, self.result_queue, max_memory_mb),
                )
                process.start()
                self.process = process
            finally:
                for env_key, prev_value in previous_env.items():
                    if prev_value is None:
                        os.environ.pop(env_key, None)
                        continue
                    os.environ[env_key] = prev_value
        self.is_running = True
        logger.info(
            f'Engine started for analysis {self.analysis_id} '
            f'(threads: {max_threads or "auto"}, memory: {max_memory_mb or "unlimited"} MB, '
            f'chunk_size: {streaming_chunk_size or "auto"})'
        )

    def preview(
        self,
        datasource_config: dict,
        pipeline_steps: list[dict],
        row_limit: int = 1000,
        offset: int = 0,
        additional_datasources: dict[str, dict] | None = None,
    ) -> str:
        """Preview pipeline results with limited rows.

        Args:
            datasource_config: Configuration for the main datasource
            pipeline_steps: List of pipeline transformation steps
            row_limit: Maximum rows to return for display
            offset: Row offset for pagination
            additional_datasources: Dict of datasource_id -> config for additional datasources
        """
        job_id = str(uuid.uuid4())
        self.current_job_id = job_id

        # Check health and restart if needed
        self.check_health()
        if not self.is_running:
            self.start()

        command = {
            'type': 'preview',
            'job_id': job_id,
            'datasource_config': datasource_config,
            'pipeline_steps': pipeline_steps,
            'row_limit': row_limit,
            'offset': offset,
            'additional_datasources': additional_datasources or {},
        }

        self.command_queue.put(command)
        return job_id

    def export(
        self,
        datasource_config: dict,
        pipeline_steps: list[dict],
        output_path: str,
        export_format: str = 'csv',
        additional_datasources: dict[str, dict] | None = None,
    ) -> str:
        """Export full pipeline results to file.

        Args:
            datasource_config: Configuration for the main datasource
            pipeline_steps: List of pipeline transformation steps
            output_path: Path to write the exported file
            export_format: Export format (csv, parquet, json, ndjson)
            additional_datasources: Dict of datasource_id -> config for additional datasources
        """
        job_id = str(uuid.uuid4())
        self.current_job_id = job_id

        # Check health and restart if needed
        self.check_health()
        if not self.is_running:
            self.start()

        command = {
            'type': 'export',
            'job_id': job_id,
            'datasource_config': datasource_config,
            'pipeline_steps': pipeline_steps,
            'output_path': output_path,
            'export_format': export_format,
            'additional_datasources': additional_datasources or {},
        }

        self.command_queue.put(command)
        return job_id

    def get_schema(
        self,
        datasource_config: dict,
        pipeline_steps: list[dict],
        additional_datasources: dict[str, dict] | None = None,
    ) -> str:
        """Get schema of pipeline result without collecting full data.

        Args:
            datasource_config: Configuration for the main datasource
            pipeline_steps: List of pipeline transformation steps
            additional_datasources: Dict of datasource_id -> config for additional datasources
        """
        job_id = str(uuid.uuid4())
        self.current_job_id = job_id

        # Check health and restart if needed
        self.check_health()
        if not self.is_running:
            self.start()

        command = {
            'type': 'schema',
            'job_id': job_id,
            'datasource_config': datasource_config,
            'pipeline_steps': pipeline_steps,
            'additional_datasources': additional_datasources or {},
        }

        self.command_queue.put(command)
        return job_id

    def get_result(self, timeout: float = 1.0, job_id: str | None = None) -> dict | None:
        """Get result from result queue (non-blocking)."""
        # Check if process died while we were waiting for a result
        if self.current_job_id and not self.is_process_alive():
            exit_code = self.process.exitcode if self.process else None
            self._reset_state()
            return {
                'data': None,
                'error': f'Compute process died unexpectedly (exit code: {exit_code}). '
                'This may be due to out of memory or another system error.',
                'job_id': job_id,
            }

        expected = job_id or self.current_job_id
        if expected and expected in self._pending_results:
            result = self._pending_results.pop(expected)
            if expected == self.current_job_id and (result.get('data') is not None or result.get('error')):
                self.current_job_id = None
            return result

        deadline = time.monotonic() + timeout
        while True:
            remaining = max(0.0, deadline - time.monotonic())
            if remaining == 0:
                return None
            try:
                result = self.result_queue.get(timeout=remaining)
            except Empty:
                return None
            except Exception as e:
                logger.warning(f'Error getting result from queue: {e}', exc_info=True)
                return None
            if not isinstance(result, dict):
                return result
            result_job = result.get('job_id')
            if expected and result_job and result_job != expected:
                self._pending_results[result_job] = result
                continue
            if expected == self.current_job_id and (result.get('data') is not None or result.get('error')):
                self.current_job_id = None
            return result

    def shutdown(self) -> None:
        """Shutdown the compute subprocess."""
        if not self.is_running:
            return

        try:
            self.command_queue.put({'type': 'shutdown'}, timeout=1)
        except Exception as exc:
            logger.warning(f'Failed to enqueue shutdown command: {exc}', exc_info=True)

        if self.process and self.process.is_alive():
            self.process.join(timeout=5)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=2)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(timeout=1)

        self.is_running = False
        self.process = None

    @staticmethod
    def _run_compute(command_queue: mp.Queue, result_queue: mp.Queue, max_memory_mb: int = 0) -> None:
        """Main compute loop running in subprocess."""
        if max_memory_mb > 0:
            memory_bytes = max_memory_mb * 1024 * 1024
            try:
                resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
                logger.debug(f'Set memory limit to {max_memory_mb} MB')
            except (OSError, ValueError) as e:
                logger.warning(f'Failed to set memory limit: {e}')

        logger.info(f'Polars compute subprocess started (PID: {os.getpid()})')

        while True:
            try:
                try:
                    command = command_queue.get(timeout=1)
                except Empty:
                    continue

                if command['type'] == 'shutdown':
                    break

                job_id = command['job_id']
                datasource_config = command['datasource_config']
                pipeline_steps = command['pipeline_steps']
                additional_datasources = command.get('additional_datasources', {})

                logger.debug(f'Job {job_id}: Starting {command["type"]} operation')

                try:
                    step_timings: dict[str, float] = {}
                    query_plan = None
                    if command['type'] == 'preview':
                        row_limit = command.get('row_limit', 1000)
                        offset = command.get('offset', 0)
                        result_data = PolarsComputeEngine._execute_preview(
                            datasource_config,
                            pipeline_steps,
                            row_limit,
                            offset,
                            job_id,
                            additional_datasources,
                        )
                    elif command['type'] == 'export':
                        output_path = command['output_path']
                        export_format = command.get('export_format', 'csv')
                        result_data = PolarsComputeEngine._execute_export(
                            datasource_config,
                            pipeline_steps,
                            output_path,
                            export_format,
                            job_id,
                            additional_datasources,
                        )
                    elif command['type'] == 'schema':
                        result_data = PolarsComputeEngine._execute_schema(
                            datasource_config,
                            pipeline_steps,
                            job_id,
                            additional_datasources,
                        )
                    else:
                        raise ValueError(f'Unknown command type: {command["type"]}')

                    if isinstance(result_data, dict):
                        step_timings = result_data.pop('step_timings', step_timings)
                        query_plan = result_data.pop('query_plan', query_plan)

                    logger.debug(f'Job {job_id}: Completed successfully')
                    result_queue.put(
                        {
                            'job_id': job_id,
                            'data': result_data,
                            'error': None,
                            'step_timings': step_timings,
                            'query_plan': query_plan,
                        }
                    )

                except Exception as e:
                    logger.error(f'Job {job_id}: Failed with error: {e}', exc_info=True)
                    result_queue.put(
                        {
                            'job_id': job_id,
                            'data': None,
                            'error': str(e),
                            'step_timings': {},
                            'query_plan': None,
                        }
                    )

            except Exception as e:
                logger.error(f'Compute loop error: {e}', exc_info=True)
                result_queue.put(
                    {
                        'job_id': None,
                        'data': None,
                        'error': f'Compute loop error: {str(e)}',
                        'step_timings': {},
                        'query_plan': None,
                    }
                )

    @staticmethod
    def build_pipeline(
        datasource_config: dict,
        pipeline_steps: list[dict],
        job_id: str,
        additional_datasources: dict[str, dict] | None = None,
    ) -> pl.LazyFrame:
        lf, _step_timings, _plan_frames = PolarsComputeEngine._build_pipeline(
            datasource_config,
            pipeline_steps,
            job_id,
            additional_datasources,
        )
        return lf

    @staticmethod
    def _build_pipeline(
        datasource_config: dict,
        pipeline_steps: list[dict],
        job_id: str,
        additional_datasources: dict[str, dict] | None = None,
    ) -> tuple[pl.LazyFrame, dict[str, float], list[pl.LazyFrame]]:
        lf = load_datasource(datasource_config)

        right_sources: dict[str, pl.LazyFrame] = {}
        if additional_datasources:
            for ds_id, ds_config in additional_datasources.items():
                try:
                    right_sources[ds_id] = load_datasource(ds_config)
                except Exception as e:
                    logger.error(f'Failed to load additional datasource {ds_id}: {e}', exc_info=True)
                    raise PipelineValidationError(
                        f'Failed to load datasource {ds_id}: {e}',
                        details={'datasource_id': ds_id},
                    ) from e

        for step in pipeline_steps:
            deps = step.get('depends_on') or []
            if len(deps) > 1:
                step_id = step.get('id') or ''
                raise PipelineValidationError(
                    f'Step {step_id} has multiple dependencies. Merge steps are not supported.',
                    step_id=str(step_id),
                )

        pipeline_steps = apply_pipeline_steps(pipeline_steps)

        if not pipeline_steps:
            return lf, {}, [lf]

        step_map: dict[str, dict] = {}
        for step in pipeline_steps:
            step_id = step.get('id')
            if not step_id:
                raise ValueError('Each pipeline step must include an id')
            step_map[step_id] = step

        dependency_map: dict[str, str | None] = {}
        dependents: dict[str, list[str]] = {}
        in_degree: dict[str, int] = {step_id: 0 for step_id in step_map}

        for step_id, step in step_map.items():
            deps = step.get('depends_on') or []
            if len(deps) > 1:
                raise PipelineValidationError(
                    f'Step {step_id} has multiple dependencies. Merge steps are not supported.',
                    step_id=step_id,
                )

            if len(deps) == 0:
                dependency_map[step_id] = None
                continue

            dep_id = deps[0]
            if dep_id not in step_map:
                raise PipelineValidationError(
                    f'Step {step_id} depends on missing step {dep_id}.',
                    step_id=step_id,
                    details={'missing_step_id': dep_id},
                )

            dependency_map[step_id] = dep_id
            dependents.setdefault(dep_id, []).append(step_id)
            in_degree[step_id] = in_degree.get(step_id, 0) + 1

        queue = [step_id for step_id, degree in in_degree.items() if degree == 0]
        ordered_steps: list[dict] = []
        while queue:
            current_id = queue.pop(0)
            ordered_steps.append(step_map[current_id])
            for child_id in dependents.get(current_id, []):
                in_degree[child_id] = in_degree.get(child_id, 0) - 1
                if in_degree[child_id] == 0:
                    queue.append(child_id)

        if len(ordered_steps) != len(step_map):
            raise PipelineValidationError('Pipeline contains a cycle. Remove cyclic dependencies to continue.')

        schema_map: dict[str, pl.LazyFrame] = {}
        total_steps = len(ordered_steps)
        step_timings: dict[str, float] = {}
        plan_frames: list[pl.LazyFrame] = []

        for idx, step in enumerate(ordered_steps):
            # Convert frontend format to backend format
            step_type = step.get('type') or ''
            try:
                convert_config_to_params(step_type, step.get('config', {}))
                backend_step = convert_step_format(step)
            except Exception as e:
                logger.error(f'Failed to convert step {idx}: {e}', exc_info=True)
                raise PipelineValidationError(
                    f'Step conversion failed: {str(e)}',
                    step_id=str(step.get('id') or ''),
                    details={'operation': step.get('type')},
                ) from e
            progress = (idx + 1) / total_steps
            step_name = backend_step.get('name', f'Step {idx + 1}')
            logger.debug(f'Job {job_id}: Processing {step_name} ({progress:.0%})')

            step_id = step.get('id')
            if not step_id:
                raise ValueError('Each pipeline step must include an id')

            parent_id = dependency_map.get(step_id)
            if parent_id is not None:
                parent_frame = schema_map.get(parent_id)
                if parent_frame is None:
                    raise ValueError(f'Missing parent frame for step {step_id}')
            else:
                parent_frame = lf

            right_source_id = backend_step.get('params', {}).get('right_source')
            right_lf = right_sources.get(right_source_id) if right_source_id else None

            step_start = time.perf_counter()
            schema_map[step_id] = PolarsComputeEngine._apply_step(
                parent_frame,
                backend_step,
                right_sources=right_sources,
                right_lf=right_lf,
            )
            timing_label = step_type or f'step_{idx + 1}'
            if timing_label in step_timings:
                counter = 2
                while f'{timing_label}_{counter}' in step_timings:
                    counter += 1
                timing_label = f'{timing_label}_{counter}'
            step_timings[timing_label] = (time.perf_counter() - step_start) * 1000

        # Return the final LazyFrame
        last_step = ordered_steps[-1]
        last_id = last_step.get('id')
        if not last_id:
            raise ValueError('Each pipeline step must include an id')
        last_frame = schema_map.get(last_id)
        if last_frame is None:
            raise ValueError(f'Missing frame for step {last_id}')

        last_type = last_step.get('type', '')
        if last_type == 'chart' or str(last_type).startswith('plot_'):
            chart_config = last_step.get('config', {})
            if str(last_type).startswith('plot_'):
                chart_sub = str(last_type).replace('plot_', '')
                chart_config = {**chart_config, 'chart_type': chart_sub}
            try:
                backend_params = convert_config_to_params(
                    'chart',
                    chart_config,
                )
            except ValueError:
                backend_params = chart_config
            last_frame = compute_chart_data(last_frame, backend_params)

        plan_frames.append(last_frame)

        return last_frame, step_timings, plan_frames

    @staticmethod
    def _merge_query_plans(plans: list[dict | None]) -> dict | None:
        if not plans:
            return None
        optimized_parts: list[str] = []
        unoptimized_parts: list[str] = []
        for plan in plans:
            if not plan:
                continue
            optimized = plan.get('optimized')
            unoptimized = plan.get('unoptimized')
            if isinstance(optimized, str):
                optimized_parts.append(optimized)
            if isinstance(unoptimized, str):
                unoptimized_parts.append(unoptimized)

        if not optimized_parts and not unoptimized_parts:
            return None
        return {
            'optimized': ''.join(optimized_parts),
            'unoptimized': ''.join(unoptimized_parts),
        }

    @staticmethod
    def _get_query_plans(lf: pl.LazyFrame) -> dict | None:
        if not hasattr(lf, 'explain'):
            return None

        optimized = lf.explain(optimized=True)
        unoptimized = lf.explain(optimized=False)

        return {
            'optimized': optimized,
            'unoptimized': unoptimized,
        }

    @staticmethod
    def _execute_preview(
        datasource_config: dict,
        pipeline_steps: list[dict],
        row_limit: int,
        offset: int,
        job_id: str,
        additional_datasources: dict[str, dict] | None = None,
    ) -> dict:
        """Execute pipeline and return limited rows for preview."""
        lf, step_timings, plan_frames = PolarsComputeEngine._build_pipeline(
            datasource_config,
            pipeline_steps,
            job_id,
            additional_datasources,
        )
        plan_segments = [PolarsComputeEngine._get_query_plans(frame) for frame in list(plan_frames)]
        query_plans = PolarsComputeEngine._merge_query_plans(plan_segments)
        query_plan = query_plans.get('optimized') if query_plans else None

        # Get schema from lazy frame (no collection needed)
        schema_obj = lf.collect_schema()
        schema = {col: str(dtype) for col, dtype in schema_obj.items()}
        lf = normalize_timezones(lf, schema_obj)

        # Collect only the rows we need for preview
        preview_df = lf.slice(offset, row_limit).collect()

        return {
            'schema': schema,
            'row_count': preview_df.height,  # Rows in this preview page
            'data': preview_df.to_dicts(),
            'query_plan': query_plan,
            'query_plans': query_plans,
            'step_timings': step_timings,
        }

    @staticmethod
    def _execute_export(
        datasource_config: dict,
        pipeline_steps: list[dict],
        output_path: str,
        export_format: str,
        job_id: str,
        additional_datasources: dict[str, dict] | None = None,
    ) -> dict:
        """Execute pipeline and write full results to file."""
        lf, step_timings, plan_frames = PolarsComputeEngine._build_pipeline(
            datasource_config,
            pipeline_steps,
            job_id,
            additional_datasources,
        )
        plan_segments = [PolarsComputeEngine._get_query_plans(frame) for frame in list(plan_frames)]
        query_plans = PolarsComputeEngine._merge_query_plans(plan_segments)
        query_plan = query_plans.get('optimized') if query_plans else None

        logger.debug(f'Job {job_id}: Writing export file')

        # Collect full dataset and write to file
        df = lf.collect()
        row_count = len(df)

        fmt = get_export_format(export_format)
        fmt.writer(df, output_path)

        return {
            'output_path': output_path,
            'export_format': export_format,
            'row_count': row_count,
            'query_plan': query_plan,
            'query_plans': query_plans,
            'step_timings': step_timings,
        }

    @staticmethod
    def _execute_schema(
        datasource_config: dict,
        pipeline_steps: list[dict],
        job_id: str,
        additional_datasources: dict[str, dict] | None = None,
    ) -> dict:
        """Execute pipeline and return schema without collecting full data."""
        lf, step_timings, plan_frames = PolarsComputeEngine._build_pipeline(
            datasource_config,
            pipeline_steps,
            job_id,
            additional_datasources,
        )

        # Get schema from lazy frame (no full collection needed)
        schema_obj = lf.collect_schema()
        schema = {col: str(dtype) for col, dtype in schema_obj.items()}

        plan_segments = [PolarsComputeEngine._get_query_plans(frame) for frame in list(plan_frames)]
        query_plans = PolarsComputeEngine._merge_query_plans(plan_segments)
        query_plan = query_plans.get('optimized') if query_plans else None

        return {
            'schema': schema,
            'columns': list(schema.keys()),
            'step_timings': step_timings,
            'query_plan': query_plan,
            'query_plans': query_plans,
        }

    @staticmethod
    def _apply_step(
        lf: pl.LazyFrame,
        step: dict,
        right_sources: dict[str, pl.LazyFrame] | None = None,
        right_lf: pl.LazyFrame | None = None,
    ) -> pl.LazyFrame:
        """Apply a single transformation step to the LazyFrame."""
        operation = step.get('operation')
        if not isinstance(operation, str) or not operation:
            raise ValueError('Step operation is required')
        params = step.get('params', {})

        handlers = get_operation_handlers()
        handler = handlers.get(operation)

        if not handler:
            raise ValueError(f'Unsupported operation: {operation}')

        return handler(lf, params, right_lf=right_lf, right_sources=right_sources)
