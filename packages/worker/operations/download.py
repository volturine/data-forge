"""Download operation - downloads the LazyFrame at any point in the pipeline."""

from dataforge_protocol import enums_pb2
from runtime.domain.compute.base import OperationParams


class DownloadParams(OperationParams):
    format: int = enums_pb2.EXPORT_FORMAT_CSV
    filename: str = "download"
