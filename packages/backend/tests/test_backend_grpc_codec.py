from __future__ import annotations

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
