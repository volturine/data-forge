import logging
import multiprocessing as mp
import uuid
from queue import Empty

import polars as pl

from modules.compute.schemas import JobStatus
from modules.compute.step_converter import convert_step_format

logger = logging.getLogger(__name__)


class PolarsComputeEngine:
    def __init__(self, analysis_id: str):
        self.analysis_id = analysis_id
        self.process: mp.Process | None = None
        self.command_queue: mp.Queue = mp.Queue()
        self.result_queue: mp.Queue = mp.Queue()
        self.is_running = False
        self.current_job_id: str | None = None

    def start(self) -> None:
        """Start the compute subprocess."""
        if self.is_running:
            return

        self.process = mp.Process(
            target=self._run_compute,
            args=(self.command_queue, self.result_queue),
        )
        self.process.start()
        self.is_running = True

    def execute(self, datasource_config: dict, pipeline_steps: list[dict], timeout: int = 300) -> str:
        """Execute a Polars pipeline in the subprocess."""
        job_id = str(uuid.uuid4())
        self.current_job_id = job_id

        if not self.is_running:
            self.start()

        command = {
            'type': 'execute',
            'job_id': job_id,
            'datasource_config': datasource_config,
            'pipeline_steps': pipeline_steps,
            'timeout': timeout,
        }

        self.command_queue.put(command)
        return job_id

    def get_result(self, timeout: float = 1.0) -> dict | None:
        """Get result from result queue (non-blocking)."""
        try:
            return self.result_queue.get(timeout=timeout)
        except Empty:
            return None
        except Exception as e:
            logger.warning(f'Error getting result from queue: {e}')
            return None

    def shutdown(self) -> None:
        """Shutdown the compute subprocess."""
        if not self.is_running:
            return

        self.command_queue.put({'type': 'shutdown'})

        if self.process and self.process.is_alive():
            self.process.join(timeout=5)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=2)
            if self.process.is_alive():
                self.process.kill()

        self.is_running = False
        self.process = None

    @staticmethod
    def _run_compute(command_queue: mp.Queue, result_queue: mp.Queue) -> None:
        """Main compute loop running in subprocess."""
        while True:
            try:
                command = command_queue.get()

                if command['type'] == 'shutdown':
                    break

                if command['type'] == 'execute':
                    job_id = command['job_id']
                    datasource_config = command['datasource_config']
                    pipeline_steps = command['pipeline_steps']

                    result_queue.put(
                        {
                            'job_id': job_id,
                            'status': JobStatus.RUNNING,
                            'progress': 0.0,
                            'current_step': 'Loading data',
                            'error': None,
                        }
                    )

                    try:
                        result_data = PolarsComputeEngine._execute_pipeline(
                            datasource_config,
                            pipeline_steps,
                            job_id,
                            result_queue,
                        )

                        result_queue.put(
                            {
                                'job_id': job_id,
                                'status': JobStatus.COMPLETED,
                                'progress': 1.0,
                                'current_step': None,
                                'data': result_data,
                                'error': None,
                            }
                        )

                    except Exception as e:
                        result_queue.put(
                            {
                                'job_id': job_id,
                                'status': JobStatus.FAILED,
                                'progress': 0.0,
                                'current_step': None,
                                'error': str(e),
                            }
                        )

            except Exception as e:
                result_queue.put(
                    {
                        'job_id': 'unknown',
                        'status': JobStatus.FAILED,
                        'progress': 0.0,
                        'current_step': None,
                        'error': f'Compute loop error: {str(e)}',
                    }
                )

    @staticmethod
    def _execute_pipeline(
        datasource_config: dict,
        pipeline_steps: list[dict],
        job_id: str,
        result_queue: mp.Queue,
    ) -> dict:
        """Execute the Polars transformation pipeline."""
        lf = PolarsComputeEngine._load_datasource(datasource_config)

        total_steps = len(pipeline_steps)

        for idx, step in enumerate(pipeline_steps):
            # Convert frontend format to backend format
            try:
                backend_step = convert_step_format(step)
            except Exception as e:
                logger.error(f'Failed to convert step {idx}: {e}')
                result_queue.put(
                    {
                        'job_id': job_id,
                        'status': JobStatus.FAILED,
                        'progress': 0.0,
                        'current_step': None,
                        'error': f'Step conversion failed: {str(e)}',
                    }
                )
                raise

            progress = (idx + 1) / total_steps
            step_name = backend_step.get('name', f'Step {idx + 1}')

            result_queue.put(
                {
                    'job_id': job_id,
                    'status': JobStatus.RUNNING,
                    'progress': progress,
                    'current_step': step_name,
                    'error': None,
                }
            )

            lf = PolarsComputeEngine._apply_step(lf, backend_step)

        # Only collect at the very end
        df = lf.collect()

        output = {
            'schema': {col: str(dtype) for col, dtype in df.schema.items()},
            'row_count': len(df),
            'sample_data': df.head(5000).to_dicts(),
        }

        return output

    @staticmethod
    def _load_datasource(config: dict) -> pl.LazyFrame:
        """Load data from datasource configuration using lazy evaluation."""
        source_type = config.get('source_type', 'file')

        if source_type == 'file':
            file_path = config['file_path']
            file_type = config['file_type']

            if file_type == 'csv':
                return pl.scan_csv(file_path)
            elif file_type == 'parquet':
                return pl.scan_parquet(file_path)
            elif file_type == 'json':
                return pl.scan_ndjson(file_path)
            else:
                raise ValueError(f'Unsupported file type: {file_type}')

        elif source_type == 'database':
            connection_string = config['connection_string']
            query = config['query']
            # Database reads need to be collected, then converted to lazy
            return pl.read_database(query, connection_string).lazy()

        else:
            raise ValueError(f'Unsupported source type: {source_type}')

    @staticmethod
    def _apply_step(lf: pl.LazyFrame, step: dict) -> pl.LazyFrame:
        """Apply a single transformation step to the LazyFrame."""
        operation = step.get('operation')
        params = step.get('params', {})

        if operation == 'filter':
            conditions = params.get('conditions', [])
            logic = params.get('logic', 'AND')

            if not conditions:
                raise ValueError('Filter requires at least one condition')

            # Build expression for each condition
            exprs = []
            for cond in conditions:
                column = cond['column']
                operator = cond.get('operator', '==')
                value = cond['value']

                col = pl.col(column)

                # Build appropriate Polars expression based on operator
                if operator == '=' or operator == '==':
                    expr = col == value
                elif operator == '!=':
                    expr = col != value
                elif operator == '>':
                    expr = col > value
                elif operator == '<':
                    expr = col < value
                elif operator == '>=':
                    expr = col >= value
                elif operator == '<=':
                    expr = col <= value
                elif operator == 'contains':
                    expr = col.str.contains(value)
                elif operator == 'starts_with':
                    expr = col.str.starts_with(value)
                elif operator == 'ends_with':
                    expr = col.str.ends_with(value)
                else:
                    raise ValueError(f'Unsupported filter operator: {operator}')

                exprs.append(expr)

            # Combine expressions with AND or OR logic
            if len(exprs) == 1:
                final_expr = exprs[0]
            elif logic == 'AND':
                final_expr = exprs[0]
                for expr in exprs[1:]:
                    final_expr = final_expr & expr
            elif logic == 'OR':
                final_expr = exprs[0]
                for expr in exprs[1:]:
                    final_expr = final_expr | expr
            else:
                raise ValueError(f'Unsupported logic operator: {logic}')

            return lf.filter(final_expr)

        elif operation == 'select':
            columns = params.get('columns', [])
            return lf.select(columns)

        elif operation == 'groupby':
            group_cols = params.get('group_by', [])
            agg_cols = params.get('aggregations', [])

            agg_exprs = []
            for agg in agg_cols:
                col = agg['column']
                func = agg['function']

                if func == 'sum':
                    agg_exprs.append(pl.col(col).sum().alias(f'{col}_sum'))
                elif func == 'mean':
                    agg_exprs.append(pl.col(col).mean().alias(f'{col}_mean'))
                elif func == 'count':
                    agg_exprs.append(pl.col(col).count().alias(f'{col}_count'))
                elif func == 'min':
                    agg_exprs.append(pl.col(col).min().alias(f'{col}_min'))
                elif func == 'max':
                    agg_exprs.append(pl.col(col).max().alias(f'{col}_max'))

            return lf.group_by(group_cols).agg(agg_exprs)

        elif operation == 'sort':
            columns = params.get('columns', [])
            descending = params.get('descending', False)
            return lf.sort(columns, descending=descending)

        elif operation == 'rename':
            mapping = params.get('mapping', {})
            return lf.rename(mapping)

        elif operation == 'with_columns':
            expressions = params.get('expressions', [])
            new_cols = []

            for expr in expressions:
                col_name = expr['name']
                expr_type = expr['type']

                if expr_type == 'literal':
                    new_cols.append(pl.lit(expr['value']).alias(col_name))
                elif expr_type == 'column':
                    new_cols.append(pl.col(expr['column']).alias(col_name))

            return lf.with_columns(new_cols)

        elif operation == 'drop':
            columns = params.get('columns', [])
            return lf.drop(columns)

        elif operation == 'pivot':
            index = params.get('index', [])
            on = params.get('columns')
            values = params.get('values')
            aggregate_function = params.get('aggregate_function', 'first')

            return lf.pivot(on=on, index=index, values=values, aggregate_function=aggregate_function)

        elif operation == 'timeseries':
            column = params.get('column')
            operation_type = params.get('operation_type')
            new_column = params.get('new_column')

            if operation_type == 'extract':
                component = params.get('component')
                if component == 'year':
                    return lf.with_columns(pl.col(column).dt.year().alias(new_column))
                elif component == 'month':
                    return lf.with_columns(pl.col(column).dt.month().alias(new_column))
                elif component == 'day':
                    return lf.with_columns(pl.col(column).dt.day().alias(new_column))
                elif component == 'hour':
                    return lf.with_columns(pl.col(column).dt.hour().alias(new_column))
                elif component == 'minute':
                    return lf.with_columns(pl.col(column).dt.minute().alias(new_column))
                elif component == 'second':
                    return lf.with_columns(pl.col(column).dt.second().alias(new_column))
                elif component == 'quarter':
                    return lf.with_columns(pl.col(column).dt.quarter().alias(new_column))
                elif component == 'week':
                    return lf.with_columns(pl.col(column).dt.week().alias(new_column))
                elif component == 'dayofweek':
                    return lf.with_columns(pl.col(column).dt.weekday().alias(new_column))
                else:
                    raise ValueError(f'Unsupported time component: {component}')

            elif operation_type == 'add':
                value = params.get('value')
                unit = params.get('unit', 'days')

                if unit == 'days':
                    duration = pl.duration(days=value)
                elif unit == 'weeks':
                    duration = pl.duration(weeks=value)
                elif unit == 'hours':
                    duration = pl.duration(hours=value)
                elif unit == 'minutes':
                    duration = pl.duration(minutes=value)
                elif unit == 'seconds':
                    duration = pl.duration(seconds=value)
                else:
                    raise ValueError(f'Unsupported time unit: {unit}')

                return lf.with_columns((pl.col(column) + duration).alias(new_column))

            elif operation_type == 'subtract':
                value = params.get('value')
                unit = params.get('unit', 'days')

                if unit == 'days':
                    duration = pl.duration(days=value)
                elif unit == 'weeks':
                    duration = pl.duration(weeks=value)
                elif unit == 'hours':
                    duration = pl.duration(hours=value)
                elif unit == 'minutes':
                    duration = pl.duration(minutes=value)
                elif unit == 'seconds':
                    duration = pl.duration(seconds=value)
                else:
                    raise ValueError(f'Unsupported time unit: {unit}')

                return lf.with_columns((pl.col(column) - duration).alias(new_column))

            elif operation_type == 'diff':
                column2 = params.get('column2')
                return lf.with_columns((pl.col(column2) - pl.col(column)).alias(new_column))

            else:
                raise ValueError(f'Unsupported timeseries operation: {operation_type}')

        elif operation == 'string_transform':
            column = params.get('column')
            method = params.get('method')
            new_column = params.get('new_column', column)

            if method == 'uppercase':
                return lf.with_columns(pl.col(column).str.to_uppercase().alias(new_column))
            elif method == 'lowercase':
                return lf.with_columns(pl.col(column).str.to_lowercase().alias(new_column))
            elif method == 'title':
                return lf.with_columns(pl.col(column).str.to_titlecase().alias(new_column))
            elif method == 'strip':
                return lf.with_columns(pl.col(column).str.strip_chars().alias(new_column))
            elif method == 'lstrip':
                return lf.with_columns(pl.col(column).str.strip_chars_start().alias(new_column))
            elif method == 'rstrip':
                return lf.with_columns(pl.col(column).str.strip_chars_end().alias(new_column))
            elif method == 'length':
                return lf.with_columns(pl.col(column).str.len_chars().alias(new_column))
            elif method == 'slice':
                start = params.get('start', 0)
                end = params.get('end')
                return lf.with_columns(pl.col(column).str.slice(start, end).alias(new_column))
            elif method == 'replace':
                pattern = params.get('pattern')
                replacement = params.get('replacement', '')
                return lf.with_columns(pl.col(column).str.replace_all(pattern, replacement).alias(new_column))
            elif method == 'extract':
                pattern = params.get('pattern')
                group_index = params.get('group_index', 0)
                return lf.with_columns(pl.col(column).str.extract(pattern, group_index).alias(new_column))
            elif method == 'split':
                delimiter = params.get('delimiter', ' ')
                index = params.get('index', 0)
                return lf.with_columns(pl.col(column).str.split(delimiter).list.get(index).alias(new_column))
            else:
                raise ValueError(f'Unsupported string method: {method}')

        elif operation == 'fill_null':
            strategy = params.get('strategy')
            columns = params.get('columns', None)

            if strategy == 'literal':
                value = params.get('value')
                if columns:
                    return lf.with_columns([pl.col(c).fill_null(value) for c in columns])
                return lf.fill_null(value)

            elif strategy == 'forward':
                if columns:
                    return lf.with_columns([pl.col(c).forward_fill() for c in columns])
                return lf.select([pl.all().forward_fill()])

            elif strategy == 'backward':
                if columns:
                    return lf.with_columns([pl.col(c).backward_fill() for c in columns])
                return lf.select([pl.all().backward_fill()])

            elif strategy == 'mean':
                if not columns:
                    raise ValueError('Columns must be specified for mean strategy')
                # Compute stats separately (requires collection)
                stats = lf.select([pl.col(c).mean().alias(c) for c in columns]).collect()
                exprs = []
                for c in columns:
                    mean_val = stats[c][0]
                    exprs.append(pl.col(c).fill_null(mean_val))
                return lf.with_columns(exprs)

            elif strategy == 'median':
                if not columns:
                    raise ValueError('Columns must be specified for median strategy')
                # Compute stats separately (requires collection)
                stats = lf.select([pl.col(c).median().alias(c) for c in columns]).collect()
                exprs = []
                for c in columns:
                    median_val = stats[c][0]
                    exprs.append(pl.col(c).fill_null(median_val))
                return lf.with_columns(exprs)

            elif strategy == 'drop_rows':
                if columns:
                    return lf.drop_nulls(subset=columns)
                return lf.drop_nulls()

            else:
                raise ValueError(f'Unsupported fill_null strategy: {strategy}')

        elif operation == 'deduplicate':
            subset = params.get('subset', None)
            keep = params.get('keep', 'first')

            return lf.unique(subset=subset, keep=keep, maintain_order=True)

        elif operation == 'explode':
            columns = params.get('columns')
            if isinstance(columns, str):
                columns = [columns]
            return lf.explode(columns)

        elif operation == 'view':
            # View is a passthrough operation for visualization purposes
            # It doesn't modify the data, just allows previewing at this step
            return lf

        else:
            raise ValueError(f'Unsupported operation: {operation}')
