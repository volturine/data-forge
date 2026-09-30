from __future__ import annotations

from pathlib import Path

import grpc
import pytest

from backend_core.data_plane_client import (
    _OBJECT_TRANSFER_CHUNK_BYTES,
    WorkerDataPlaneClient,
    WorkerDataPlaneError,
    _arrow_schema_proto,
    _object_store_storage_options_payload,
)
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


class _FakeDownloadCall:
    def __init__(self, chunks: list[bytes], *, error: Exception | None = None) -> None:
        self._chunks = chunks
        self._error = error
        self.cancelled = False

    def __iter__(self):
        for chunk in self._chunks:
            yield object_store_pb2.ObjectStoreTransferChunk(data=chunk)
        if self._error is not None:
            raise self._error

    def cancel(self) -> None:
        self.cancelled = True


class _CancelledRpcError(grpc.RpcError):
    def code(self):
        return grpc.StatusCode.CANCELLED

    def details(self):
        return 'download cancelled'


def _client_with_object_store(stub) -> WorkerDataPlaneClient:
    client = WorkerDataPlaneClient.__new__(WorkerDataPlaneClient)
    client._target = 'data-plane.test:50052'
    client._token = 'test-token'
    client._timeout_seconds = 1
    client._trivial_timeout_seconds = 1
    client._object_store = stub
    return client


def test_nine_megabyte_byte_upload_splits_into_bounded_wire_chunks() -> None:
    class Stub:
        def UploadObject(self, requests, **_kwargs):
            self.frames = list(requests)
            return object_store_pb2.ObjectStoreUrl(url='s3://analytics/uploads/artifact.bin')

    stub = Stub()
    client = _client_with_object_store(stub)

    result = client.upload_object_bytes(b'x' * (9 * 1024 * 1024), 's3://analytics/uploads/artifact.bin')

    assert result == 's3://analytics/uploads/artifact.bin'
    assert [frame.WhichOneof('frame') for frame in stub.frames] == ['start', 'chunk', 'chunk', 'commit']
    assert [len(frame.chunk.data) for frame in stub.frames if frame.WhichOneof('frame') == 'chunk'] == [8 * 1024 * 1024, 1024 * 1024]


def test_upload_object_file_streams_beyond_former_unary_limit(tmp_path: Path) -> None:
    class Stub:
        def UploadObject(self, requests, **_kwargs):
            self.frame_kinds = []
            self.total_bytes = 0
            self.max_chunk_bytes = 0
            for frame in requests:
                kind = frame.WhichOneof('frame')
                self.frame_kinds.append(kind)
                if kind == 'chunk':
                    chunk_size = len(frame.chunk.data)
                    self.total_bytes += chunk_size
                    self.max_chunk_bytes = max(self.max_chunk_bytes, chunk_size)
            return object_store_pb2.ObjectStoreUrl(url='s3://analytics/uploads/large-artifact.bin')

    file_size = 129 * 1024 * 1024
    source = tmp_path / 'large-artifact.bin'
    with source.open('wb') as output:
        output.truncate(file_size)

    stub = Stub()
    result = _client_with_object_store(stub).upload_object_file(
        source,
        's3://analytics/uploads/large-artifact.bin',
        max_bytes=2 * 1024 * 1024 * 1024,
    )

    assert stub.frame_kinds[0] == 'start'
    assert stub.frame_kinds[1:-1] == ['chunk'] * ((file_size + _OBJECT_TRANSFER_CHUNK_BYTES - 1) // _OBJECT_TRANSFER_CHUNK_BYTES)
    assert stub.frame_kinds[-1] == 'commit'
    assert stub.total_bytes == file_size
    assert stub.total_bytes > 128 * 1024 * 1024
    assert stub.max_chunk_bytes <= _OBJECT_TRANSFER_CHUNK_BYTES
    assert result == 's3://analytics/uploads/large-artifact.bin'


def test_closing_upload_request_generator_does_not_yield_abort_during_generator_exit() -> None:
    class Stub:
        def UploadObject(self, requests, **_kwargs):
            self.frames = [next(requests), next(requests)]
            requests.close()
            return object_store_pb2.ObjectStoreUrl(url='s3://analytics/uploads/artifact.bin')

    stub = Stub()
    client = _client_with_object_store(stub)

    result = client.upload_object_stream([b'chunk'], 's3://analytics/uploads/artifact.bin')

    assert result == 's3://analytics/uploads/artifact.bin'
    assert [frame.WhichOneof('frame') for frame in stub.frames] == ['start', 'chunk']


def test_nine_megabyte_byte_download_remains_within_artifact_limit() -> None:
    call = _FakeDownloadCall(
        [
            b'a' * (8 * 1024 * 1024),
            b'b' * (1024 * 1024),
        ]
    )

    class Stub:
        def DownloadObject(self, *_args, **_kwargs):
            return call

    payload = _client_with_object_store(Stub()).download_object_bytes('s3://analytics/exports/artifact.bin')

    assert len(payload) == 9 * 1024 * 1024
    assert payload[:1] == b'a'
    assert payload[-1:] == b'b'
    assert not call.cancelled


def test_download_file_error_preserves_destination_and_removes_partial(tmp_path: Path) -> None:
    destination = tmp_path / 'artifact.bin'
    destination.write_bytes(b'previous destination')
    contents_before_download = set(tmp_path.iterdir())
    call = _FakeDownloadCall([b'partial'], error=OSError('transfer failed'))

    class Stub:
        def DownloadObject(self, *_args, **_kwargs):
            return call

    with pytest.raises(OSError, match='transfer failed'):
        _client_with_object_store(Stub()).download_object_file('s3://analytics/exports/artifact.bin', destination)

    assert destination.read_bytes() == b'previous destination'
    contents_after_download = set(tmp_path.iterdir())
    assert contents_after_download == contents_before_download
    assert not any(path.name.endswith('.partial') for path in contents_after_download)
    assert call.cancelled


def test_cancelled_download_removes_partial_and_preserves_destination(tmp_path: Path) -> None:
    destination = tmp_path / 'artifact.bin'
    destination.write_bytes(b'previous destination')
    contents_before_download = set(tmp_path.iterdir())
    call = _FakeDownloadCall([b'partial'], error=_CancelledRpcError())

    class Stub:
        def DownloadObject(self, *_args, **_kwargs):
            return call

    with pytest.raises(WorkerDataPlaneError) as exc_info:
        _client_with_object_store(Stub()).download_object_file('s3://analytics/exports/artifact.bin', destination)

    assert exc_info.value.code == grpc.StatusCode.CANCELLED
    assert destination.read_bytes() == b'previous destination'
    contents_after_download = set(tmp_path.iterdir())
    assert contents_after_download == contents_before_download
    assert not any(path.name.endswith('.partial') for path in contents_after_download)
    assert call.cancelled


def test_closing_download_stream_cancels_rpc() -> None:
    call = _FakeDownloadCall(
        [
            b'first',
            b'second',
        ]
    )

    class Stub:
        def DownloadObject(self, *_args, **_kwargs):
            return call

    stream = _client_with_object_store(Stub()).download_object_stream('s3://analytics/exports/artifact.bin')

    assert next(stream) == b'first'
    stream.close()

    assert call.cancelled
