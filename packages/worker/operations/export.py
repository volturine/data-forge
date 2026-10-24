"""Export passthrough operation."""

from dataforge_protocol import enums_pb2
from runtime.domain.compute.base import OperationParams


class ExportParams(OperationParams):
    format: int = enums_pb2.EXPORT_FORMAT_CSV
    filename: str = "export"
    destination: int = enums_pb2.EXPORT_DESTINATION_DOWNLOAD
    iceberg_options: dict | None = None
