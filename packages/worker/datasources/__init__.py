"""Worker-owned datasource execution and loading.

This package is the only owner of Polars/Iceberg work for datasources.
Backend HTTP modules publish metadata through fenced RPCs; they do not load frames.
"""

from datasources.datasource_loading import load_datasource, load_datasource_frame

__all__ = ["load_datasource", "load_datasource_frame"]
