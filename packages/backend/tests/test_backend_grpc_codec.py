from __future__ import annotations

import pytest

from backend_core.data_plane_client import _arrow_schema_proto, _object_store_storage_options_payload
from dataforge_protocol import object_store_pb2


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
