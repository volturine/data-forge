from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from uuid import UUID

import pyarrow as pa  # type: ignore[import-untyped]
from google.protobuf import json_format

from dataforge_protocol import iceberg_pb2
from runtime.json_values import dict_to_struct
from worker_grpc.data_plane_server import _arrow_schema_from_proto


def test_worker_grpc_json_payload_normalizes_json_boundary_values() -> None:
    payload: dict[str, object] = {
        "rows": [
            {
                "event_date": date(2026, 6, 16),
                "seen_at": datetime(2026, 6, 16, 8, 30, tzinfo=UTC),
                "window_start": time(8, 30, 15),
                "amount": Decimal("42.50"),
                "count": Decimal("7"),
                "id": UUID("12345678-1234-5678-1234-567812345678"),
            },
        ],
    }

    decoded = json_format.MessageToDict(dict_to_struct(payload), preserving_proto_field_name=True)

    assert decoded == {
        "rows": [
            {
                "event_date": "2026-06-16",
                "seen_at": "2026-06-16T08:30:00+00:00",
                "window_start": "08:30:15",
                "amount": 42.5,
                "count": 7,
                "id": "12345678-1234-5678-1234-567812345678",
            },
        ],
    }


def test_worker_grpc_arrow_schema_payload_round_trips() -> None:
    schema = pa.schema([pa.field("id", pa.int64()), pa.field("name", pa.string())])
    encoded = schema.serialize().to_pybytes()

    decoded = _arrow_schema_from_proto(iceberg_pb2.ArrowSchemaIpc(payload=encoded))

    assert decoded == schema
