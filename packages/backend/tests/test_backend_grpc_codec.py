from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from uuid import UUID

import pytest

from backend_core.data_plane_client import _arrow_schema_proto, _object_store_storage_options_payload
from backend_grpc.codec import dict_to_struct, struct_to_dict
from dataforge_protocol import object_store_pb2


def test_grpc_json_payload_preserves_integer_values() -> None:
    payload: dict[str, object] = {
        'status_code': 404,
        'row_count': 12,
        'nested': {'limit': 3},
        'enabled': True,
        'missing': None,
    }

    decoded = struct_to_dict(dict_to_struct(payload))

    assert decoded == payload
    assert isinstance(decoded['status_code'], int)
    assert isinstance(decoded['row_count'], int)


def test_grpc_json_payload_normalizes_json_boundary_values() -> None:
    payload: dict[str, object] = {
        'rows': [
            {
                'event_date': date(2026, 6, 16),
                'seen_at': datetime(2026, 6, 16, 8, 30, tzinfo=UTC),
                'window_start': time(8, 30, 15),
                'amount': Decimal('42.50'),
                'count': Decimal('7'),
                'id': UUID('12345678-1234-5678-1234-567812345678'),
            },
        ],
    }

    decoded = struct_to_dict(dict_to_struct(payload))

    assert decoded == {
        'rows': [
            {
                'event_date': '2026-06-16',
                'seen_at': '2026-06-16T08:30:00+00:00',
                'window_start': '08:30:15',
                'amount': 42.5,
                'count': 7,
                'id': '12345678-1234-5678-1234-567812345678',
            },
        ],
    }


def test_data_plane_storage_options_use_typed_protocol_message() -> None:
    payload = _object_store_storage_options_payload(
        object_store_pb2.ObjectStoreStorageOptions(
            endpoint_url='http://127.0.0.1:9000',
            access_key_id='access',
            secret_access_key='secret',
            region='us-east-1',
            force_virtual_addressing=False,
            py_io_impl='pyiceberg.io.pyarrow.PyArrowFileIO',
        )
    )

    assert payload == {
        's3.endpoint': 'http://127.0.0.1:9000',
        's3.access-key-id': 'access',
        's3.secret-access-key': 'secret',
        's3.region': 'us-east-1',
        's3.force-virtual-addressing': False,
        'py-io-impl': 'pyiceberg.io.pyarrow.PyArrowFileIO',
    }


def test_data_plane_arrow_schema_rejects_non_base64_payload() -> None:
    with pytest.raises(ValueError, match='base64-encoded Arrow schema IPC'):
        _arrow_schema_proto({'arrow_schema_ipc_base64': 'not base64'})
