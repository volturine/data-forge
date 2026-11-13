"""Restricted polars surface exposed to UDF code as ``pl``.

UDF code may build expressions and frames in memory and may only read from
``s3://`` objects through the compute worker's own object-store options. The
full polars module is never exposed because it reads and writes local files,
runs SQL table functions, loads native plugins and changes global config.
"""

import inspect
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import polars as pl
import polars.selectors as cs

from datasources.datasource_loading import polars_storage_options

_S3_ONLY_MESSAGE = "UDF code may only read from s3:// paths"
_FORBIDDEN_READ_OPTIONS = frozenset({"storage_options", "credential_provider"})

# In-memory polars API: data types, frame classes and expression functions.
# ``format`` is left out because UDF code may not use the ``format`` attribute
# name (see ``validate_udf_attribute_access``).
_ALLOWED_POLARS_NAMES = (
    "Array",
    "Binary",
    "Boolean",
    "Categorical",
    "DataFrame",
    "DataType",
    "Date",
    "Datetime",
    "Decimal",
    "Duration",
    "Enum",
    "Expr",
    "Field",
    "Float32",
    "Float64",
    "Int8",
    "Int16",
    "Int32",
    "Int64",
    "Int128",
    "LazyFrame",
    "List",
    "Null",
    "Object",
    "Schema",
    "Series",
    "String",
    "Struct",
    "Time",
    "UInt8",
    "UInt16",
    "UInt32",
    "UInt64",
    "UInt128",
    "Unknown",
    "Utf8",
    "align_frames",
    "all",
    "all_horizontal",
    "any",
    "any_horizontal",
    "approx_n_unique",
    "arange",
    "arctan2",
    "arg_sort_by",
    "arg_where",
    "business_day_count",
    "coalesce",
    "col",
    "collect_all",
    "concat",
    "concat_arr",
    "concat_list",
    "concat_str",
    "corr",
    "count",
    "cov",
    "cum_count",
    "cum_fold",
    "cum_reduce",
    "cum_sum",
    "cum_sum_horizontal",
    "date",
    "date_range",
    "date_ranges",
    "datetime",
    "datetime_range",
    "datetime_ranges",
    "duration",
    "element",
    "escape_regex",
    "exclude",
    "field",
    "first",
    "fold",
    "from_dict",
    "from_dicts",
    "from_epoch",
    "from_records",
    "from_repr",
    "head",
    "implode",
    "int_range",
    "int_ranges",
    "last",
    "len",
    "linear_space",
    "linear_spaces",
    "lit",
    "map_batches",
    "map_groups",
    "max",
    "max_horizontal",
    "mean",
    "mean_horizontal",
    "median",
    "merge_sorted",
    "min",
    "min_horizontal",
    "n_unique",
    "nth",
    "ones",
    "quantile",
    "reduce",
    "repeat",
    "rolling_corr",
    "rolling_cov",
    "row_index",
    "select",
    "std",
    "struct",
    "sum",
    "sum_horizontal",
    "tail",
    "time",
    "time_range",
    "time_ranges",
    "union",
    "var",
    "when",
    "zeros",
)

# Readers whose s3:// paths go through polars' native object store, so the
# worker's storage options apply. ``read_*`` collects the matching scan, so
# its only extra option is ``columns``, applied as a select on the scan.
_S3_SCANS = {
    "read_csv": "scan_csv",
    "read_ipc": "scan_ipc",
    "read_ndjson": "scan_ndjson",
    "read_parquet": "scan_parquet",
    "scan_csv": "scan_csv",
    "scan_ipc": "scan_ipc",
    "scan_ndjson": "scan_ndjson",
    "scan_parquet": "scan_parquet",
}


def _require_s3_source(source: object) -> None:
    sources = source if isinstance(source, list | tuple) else [source]
    if not sources or not all(isinstance(item, str) and item.startswith("s3://") for item in sources):
        raise ValueError(_S3_ONLY_MESSAGE)


def _require_supported_options(scan: Callable[..., pl.LazyFrame], kwargs: dict[str, Any]) -> None:
    # Underscore options are polars internals; some take local paths, such as
    # ``scan_parquet(_deletion_files=...)``.
    private = sorted(key for key in kwargs if key.startswith("_"))
    if private:
        raise ValueError(f"UDF code cannot pass private read options: {', '.join(private)}")
    overridden = _FORBIDDEN_READ_OPTIONS.intersection(kwargs)
    if overridden:
        raise ValueError(f"UDF code cannot override {', '.join(sorted(overridden))}")
    parameters = inspect.signature(scan).parameters
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return
    unsupported = sorted(key for key in kwargs if key not in parameters)
    if unsupported:
        raise ValueError(f"Unsupported option for UDF S3 reads: {', '.join(unsupported)}")


def _select_columns(frame: pl.LazyFrame, columns: object) -> pl.LazyFrame:
    if isinstance(columns, str):
        return frame.select(columns)
    if isinstance(columns, list | tuple) and all(isinstance(column, str) for column in columns):
        return frame.select(columns)
    if isinstance(columns, list | tuple) and all(isinstance(column, int) and not isinstance(column, bool) for column in columns):
        return frame.select(pl.nth(*columns))
    raise ValueError("columns must be a list of column names or a list of column indices")


def _s3_reader(name: str, scan_name: str) -> Callable[..., pl.DataFrame | pl.LazyFrame]:
    collect = name.startswith("read_")

    def read(source: object, **kwargs: Any) -> pl.DataFrame | pl.LazyFrame:
        _require_s3_source(source)
        columns = kwargs.pop("columns", None) if collect else None
        # Look up the scan at call time; the worker's object-store settings are
        # only final after the compute worker is initialized.
        scan: Callable[..., pl.LazyFrame] = getattr(pl, scan_name)
        _require_supported_options(scan, kwargs)
        frame = scan(source, storage_options=polars_storage_options(), **kwargs)
        if columns is not None:
            frame = _select_columns(frame, columns)
        return frame.collect() if collect else frame

    read.__name__ = name
    return read


def udf_polars_namespace() -> SimpleNamespace:
    """Build the ``pl`` object for one UDF execution."""
    members: dict[str, Any] = {name: getattr(pl, name) for name in _ALLOWED_POLARS_NAMES}
    members.update({name: _s3_reader(name, scan_name) for name, scan_name in _S3_SCANS.items()})
    # polars.selectors imports modules such as ``builtins``; expose only its API.
    members["selectors"] = SimpleNamespace(**{name: getattr(cs, name) for name in cs.__all__})
    return SimpleNamespace(**members)
