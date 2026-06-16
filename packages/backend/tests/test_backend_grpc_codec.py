from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from uuid import UUID

from backend_grpc.codec import dict_to_struct, struct_to_dict


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
